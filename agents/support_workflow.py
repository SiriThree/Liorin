"""Customer verification and support workflow graph for Liorin."""

from typing import Literal, NamedTuple

from langchain.chat_models import init_chat_model
from langchain_community.utilities import SQLDatabase
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt
from typing_extensions import Annotated, TypedDict

from agents.conversation_supervisor import create_supervisor_agent
from agents.knowledge_agent import create_knowledge_agent
from agents.order_agent import create_order_agent
from config import DEFAULT_MODEL, Context
from tools.database import get_database


class IntermediateState(MessagesState):
    """MessagesState extended with a verified customer id."""

    customer_id: str


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
    """Route the request based on whether customer verification is needed."""
    if state.get("customer_id"):
        return Command(goto="supervisor_agent")

    last_message = state["messages"][-1]
    model = runtime.context.model if runtime.context is not None else DEFAULT_MODEL
    query_classification = classify_query_intent(last_message.content, model=model)

    if query_classification.get("requires_verification"):
        return Command(goto="verify_customer")
    return Command(goto="supervisor_agent")


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
            return Command(
                update={
                    "customer_id": customer.customer_id,
                    "messages": [
                        AIMessage(
                            content=f"身份验证通过。欢迎回来，{customer.customer_name}。"
                        )
                    ],
                },
                goto="supervisor_agent",
            )

        return Command(
            update={
                "messages": [
                    AIMessage(
                        content=(
                            f"系统中没有找到邮箱“{extraction['email']}”对应的客户记录。"
                            "请检查邮箱后再试一次。"
                        )
                    )
                ]
            },
            goto="collect_email",
        )

    return Command(
        update={
            "messages": [
                AIMessage(
                    content=(
                        "为了查询你的账户或订单信息，请先提供注册邮箱。"
                    )
                )
            ]
        },
        goto="collect_email",
    )


def collect_email(state: IntermediateState) -> Command[Literal["verify_customer"]]:
    """Pause the graph until the customer provides an email address."""
    user_input = interrupt(value="请提供你的注册邮箱：")
    return Command(
        update={"messages": [HumanMessage(content=user_input)]}, goto="verify_customer"
    )


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
