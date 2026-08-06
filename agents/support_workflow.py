"""Customer verification and support workflow graph for Liorin."""

from typing import Any, Literal, NamedTuple

from langchain.chat_models import init_chat_model
from langchain_community.utilities import SQLDatabase
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt
from typing_extensions import Annotated, NotRequired, TypedDict

from agents.conversation_supervisor import create_supervisor_agent
from agents.knowledge_agent import create_knowledge_agent
from agents.order_agent import create_order_agent
from config import DEFAULT_MODEL, Context
from identity import IdentityResolver
from tools.database import get_database
from memory.facts import get_default_long_term_memory_runtime
from memory.working import WorkingMemoryUpdater


class IntermediateState(MessagesState):
    """Checkpoint-safe support state consumed by the Context Runtime.

    ``messages`` remains the immutable audit/recovery history owned by
    LangGraph.  The small workflow fields below expose current task state and
    unresolved slots without introducing conversation or long-term memory.
    """

    customer_id: NotRequired[str]
    workflow_state: NotRequired[dict[str, Any]]
    unresolved_slots: NotRequired[list[str]]
    session_id: NotRequired[str]
    identity_context: NotRequired[dict[str, str]]
    working_memory: NotRequired[dict[str, Any]]
    working_memory_lifecycle_records: NotRequired[list[dict[str, Any]]]
    long_term_memory_lifecycle_records: NotRequired[list[dict[str, Any]]]
    memory_fact_candidates: NotRequired[list[dict[str, Any]]]
    user_confirmed_facts: NotRequired[dict[str, Any]]
    business_system_facts: NotRequired[dict[str, Any]]
    product_model: NotRequired[str]
    product_name: NotRequired[str]
    region: NotRequired[str]


_IDENTITY_RESOLVER = IdentityResolver()
_WORKING_MEMORY_UPDATER = WorkingMemoryUpdater()
_LONG_TERM_MEMORY_RUNTIME = get_default_long_term_memory_runtime()
_MAX_CHECKPOINT_LIFECYCLE_RECORDS = 120
_MAX_LONG_TERM_MEMORY_LIFECYCLE_RECORDS = 120


def _with_working_memory(
    state: IntermediateState,
    updates: dict[str, Any],
    *,
    actor: str,
    reason: str,
    task_goal: str | None = None,
    current_intent: str | None = None,
    memory_state: dict[str, Any] | None = None,
    runtime: Runtime[Context] | None = None,
) -> dict[str, Any]:
    """Apply workflow updates and persist compact Working Memory in state."""

    candidate_state = dict(state)
    candidate_state.update(updates)
    if task_goal is not None:
        candidate_state["task_goal"] = task_goal
    if current_intent is not None:
        candidate_state["current_intent"] = current_intent
    if memory_state:
        candidate_state.update(memory_state)

    identity_context = _IDENTITY_RESOLVER.resolve(candidate_state, runtime=runtime)
    candidate_state["identity_context"] = identity_context.to_state()
    candidate_state["session_id"] = identity_context.session_id

    existing_records = list(state.get("working_memory_lifecycle_records", []) or [])
    result = _WORKING_MEMORY_UPDATER.update(
        candidate_state,
        actor=actor,
        reason=reason,
        previous=state.get("working_memory"),
        existing_records=existing_records,
        session_id=identity_context.session_id,
        identity_context=identity_context,
    )
    new_records = result.records_to_state()
    checkpoint_updates = dict(updates)
    checkpoint_updates["identity_context"] = identity_context.to_state()
    checkpoint_updates["session_id"] = identity_context.session_id
    if new_records:
        combined_records = (existing_records + new_records)[
            -_MAX_CHECKPOINT_LIFECYCLE_RECORDS:
        ]
        checkpoint_updates["working_memory_lifecycle_records"] = combined_records
    if result.persisted:
        checkpoint_updates["working_memory"] = result.memory.to_state()

    # Promotion is structured and policy-gated. It never scans the full chat
    # history and never writes Working Memory directly into the long-term store.
    promotion_state = dict(candidate_state)
    promotion_state["working_memory"] = result.memory.to_state()
    promotion = _LONG_TERM_MEMORY_RUNTIME.promote_from_state(
        promotion_state,
        identity_context=identity_context,
        actor=actor,
        reason=reason,
        working_memory=result.memory,
    )
    promotion_records = promotion.records_to_state()
    if promotion_records:
        existing_long_term_records = list(
            state.get("long_term_memory_lifecycle_records", []) or []
        )
        checkpoint_updates["long_term_memory_lifecycle_records"] = (
            existing_long_term_records + promotion_records
        )[-_MAX_LONG_TERM_MEMORY_LIFECYCLE_RECORDS:]
    return checkpoint_updates


class QueryClassification(TypedDict):
    """判断用户问题是否需要客户身份验证。"""

    reasoning: Annotated[
        str, ..., "简要说明为什么需要或不需要身份验证"
    ]
    requires_verification: Annotated[
        bool,
        ...,
        "账户、订单、工单、质保等客户专属问题为 True；通用产品或政策问题为 False。",
    ]


class EmailExtraction(TypedDict):
    """从用户消息中抽取邮箱地址。"""

    email: Annotated[
        str,
        ...,
        "从消息中抽取到的邮箱地址；如果没有找到则返回空字符串",
    ]


class CustomerInfo(NamedTuple):
    """Customer information returned from validation."""

    customer_id: str
    customer_name: str


def classify_query_intent(query: str, model: str = DEFAULT_MODEL) -> QueryClassification:
    """Classify whether a customer query requires identity verification."""
    llm = init_chat_model(model, configurable_fields=["model"])
    structured_llm = llm.with_structured_output(QueryClassification)
    classification_prompt = (
        "请判断用户的问题是否必须知道客户身份才能回答。"
        "如果问题涉及具体账户、订单、购买记录、售后工单、质保案例、退款或维修进度，requires_verification 返回 true；"
        "如果只是询问通用产品说明、故障排查方法或售后政策，返回 false。"
        "请用中文填写 reasoning。"
    )

    return structured_llm.invoke(
        [
            {"role": "system", "content": classification_prompt},
            {"role": "user", "content": query},
        ]
    )


def create_email_extractor(model: str = DEFAULT_MODEL):
    """Create an LLM configured to extract emails from natural language."""
    llm = init_chat_model(model, configurable_fields=["model"])
    return llm.with_structured_output(EmailExtraction)


def validate_customer_email(email: str, db: SQLDatabase) -> CustomerInfo | None:
    """Validate email format and look up the customer in the database."""
    if not email or "@" not in email:
        return None

    result = db._execute(
        f"SELECT customer_id, name FROM customers WHERE email = '{email}'"
    )
    rows = [tuple(row.values()) for row in result]

    if not rows:
        return None

    customer_id, customer_name = rows[0]
    return CustomerInfo(customer_id=customer_id, customer_name=customer_name)


def query_router(
    state: IntermediateState,
    runtime: Runtime[Context],
) -> Command[Literal["verify_customer", "supervisor_agent"]]:
    """Route the request and synchronise checkpoint-safe Working Memory."""
    last_message = state["messages"][-1]
    task_goal = str(
        last_message.get("content", "")
        if isinstance(last_message, dict)
        else getattr(last_message, "content", "")
    )

    if state.get("customer_id"):
        updates = _with_working_memory(
            state,
            {
                "workflow_state": {
                    "stage": "ready_for_supervisor",
                    "requires_verification": False,
                },
                "unresolved_slots": [],
            },
            actor="support_workflow.query_router",
            reason="Route verified customer request to supervisor",
            task_goal=task_goal,
            current_intent="verified_customer_support",
            runtime=runtime,
        )
        return Command(update=updates, goto="supervisor_agent")

    model = runtime.context.model if runtime.context is not None else DEFAULT_MODEL
    query_classification = classify_query_intent(task_goal, model=model)

    if query_classification.get("requires_verification"):
        updates = _with_working_memory(
            state,
            {
                "workflow_state": {
                    "stage": "identity_verification",
                    "requires_verification": True,
                    "routing_reason": query_classification.get("reasoning", ""),
                },
                "unresolved_slots": ["customer_email"],
            },
            actor="support_workflow.query_router",
            reason="Identity verification required before account-specific work",
            task_goal=task_goal,
            current_intent="account_specific_support",
            runtime=runtime,
        )
        return Command(update=updates, goto="verify_customer")

    updates = _with_working_memory(
        state,
        {
            "workflow_state": {
                "stage": "ready_for_supervisor",
                "requires_verification": False,
                "routing_reason": query_classification.get("reasoning", ""),
            },
            "unresolved_slots": [],
        },
        actor="support_workflow.query_router",
        reason="General support request ready for supervisor",
        task_goal=task_goal,
        current_intent="general_support",
        runtime=runtime,
    )
    return Command(update=updates, goto="supervisor_agent")


def verify_customer(
    state: IntermediateState,
    runtime: Runtime[Context],
) -> Command[Literal["supervisor_agent", "collect_email"]]:
    """Collect and validate a customer email before account-specific work."""
    last_message = state["messages"][-1]
    model = runtime.context.model if runtime.context is not None else DEFAULT_MODEL
    email_extractor = create_email_extractor(model=model)
    extraction = email_extractor.invoke([last_message])

    if extraction["email"]:
        customer = validate_customer_email(extraction["email"], get_database())

        if customer:
            updates = _with_working_memory(
                state,
                {
                    "customer_id": customer.customer_id,
                    "messages": [AIMessage(content=f"身份验证通过。欢迎回来，{customer.customer_name}。")],
                    "workflow_state": {
                        "stage": "ready_for_supervisor",
                        "requires_verification": False,
                        "identity_status": "verified",
                    },
                    "unresolved_slots": [],
                },
                actor="support_workflow.verify_customer",
                reason="Customer identity verified",
                current_intent="account_specific_support",
                runtime=runtime,
            )
            return Command(update=updates, goto="supervisor_agent")

        updates = _with_working_memory(
            state,
            {
                "messages": [AIMessage(content=(
                    f"系统中没有找到邮箱“{extraction['email']}”对应的客户记录。"
                    "请检查邮箱后再试一次。"
                ))],
                "workflow_state": {
                    "stage": "identity_verification",
                    "requires_verification": True,
                    "identity_status": "not_found",
                },
                "unresolved_slots": ["customer_email"],
            },
            actor="support_workflow.verify_customer",
            reason="Customer email was not found",
            current_intent="identity_verification",
            memory_state={"failed_attempts": ["customer_email_not_found"]},
            runtime=runtime,
        )
        return Command(update=updates, goto="collect_email")

    updates = _with_working_memory(
        state,
        {
            "messages": [AIMessage(content="为了查询你的账户或订单信息，请先提供注册邮箱。")],
            "workflow_state": {
                "stage": "identity_verification",
                "requires_verification": True,
                "identity_status": "missing",
            },
            "unresolved_slots": ["customer_email"],
        },
        actor="support_workflow.verify_customer",
        reason="Customer email is still missing",
        current_intent="identity_verification",
        runtime=runtime,
    )
    return Command(update=updates, goto="collect_email")


def collect_email(state: IntermediateState) -> Command[Literal["verify_customer"]]:
    """Pause the graph until the customer provides an email address."""
    user_input = interrupt(value="请提供你的注册邮箱：")
    updates = _with_working_memory(
        state,
        {
            "messages": [HumanMessage(content=user_input)],
            "workflow_state": {
                "stage": "identity_verification",
                "requires_verification": True,
                "identity_status": "provided_for_validation",
            },
            "unresolved_slots": [],
        },
        actor="support_workflow.collect_email",
        reason="Customer provided identity slot for validation",
        current_intent="identity_verification",
        memory_state={"next_actions": ["校验客户邮箱"]},
    )
    return Command(update=updates, goto="verify_customer")


def create_support_agent(
    order_agent=None,
    knowledge_agent=None,
    use_checkpointer: bool = True,
):
    """Create the full customer support graph.

    The default graph uses an order specialist and a knowledge
    specialist behind a supervisor, with identity verification in front of
    account- and order-specific requests.
    """
    if order_agent is None:
        order_agent = create_order_agent(use_checkpointer=use_checkpointer)

    if knowledge_agent is None:
        knowledge_agent = create_knowledge_agent(use_checkpointer=use_checkpointer)

    supervisor_agent = create_supervisor_agent(
        order_agent=order_agent,
        knowledge_agent=knowledge_agent,
        state_schema=IntermediateState,
        use_checkpointer=use_checkpointer,
    )

    workflow = StateGraph(
        input_schema=MessagesState,
        state_schema=IntermediateState,
        output_schema=MessagesState,
        context_schema=Context,
    )

    workflow.add_node("query_router", query_router)
    workflow.add_node("verify_customer", verify_customer)
    workflow.add_node("collect_email", collect_email)
    workflow.add_node("supervisor_agent", supervisor_agent)
    workflow.add_edge(START, "query_router")

    if use_checkpointer:
        return workflow.compile(
            checkpointer=MemorySaver(), name="support_agent"
        )
    return workflow.compile(name="support_agent")
