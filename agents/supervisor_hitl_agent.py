"""Customer verification and supervisor graph for TechHub support."""

from typing import Literal, NamedTuple

from langchain.chat_models import init_chat_model
from langchain_community.utilities import SQLDatabase
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt
from typing_extensions import Annotated, TypedDict

from agents.docs_agent import create_docs_agent
from agents.sql_agent import create_sql_agent
from agents.supervisor_agent import create_supervisor_agent
from config import DEFAULT_MODEL, Context
from tools.database import get_database


class IntermediateState(MessagesState):
    """MessagesState extended with a verified customer id."""

    customer_id: str


class QueryClassification(TypedDict):
    """Classification of whether customer identity verification is required."""

    reasoning: Annotated[
        str, ..., "Brief explanation of why verification is or is not needed"
    ]
    requires_verification: Annotated[
        bool,
        ...,
        "True for account/order-specific requests; false for general product or policy questions.",
    ]


class EmailExtraction(TypedDict):
    """Schema for extracting an email address from a user message."""

    email: Annotated[
        str,
        ...,
        "The email address extracted from the message, or empty string if none was found",
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
        "Analyze whether the user's query requires knowing their customer "
        "identity in order to answer."
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
                            content=f"Verified. Welcome back, {customer.customer_name}."
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
                            f"I couldn't find '{extraction['email']}' in our "
                            "system. Please check and try again."
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
                        "To access information about your account or orders, "
                        "please provide your email address."
                    )
                )
            ]
        },
        goto="collect_email",
    )


def collect_email(state: IntermediateState) -> Command[Literal["verify_customer"]]:
    """Pause the graph until the customer provides an email address."""
    user_input = interrupt(value="Please provide your email:")
    return Command(
        update={"messages": [HumanMessage(content=user_input)]}, goto="verify_customer"
    )


def create_supervisor_hitl_agent(
    database_agent=None,
    docs_agent=None,
    use_checkpointer: bool = True,
):
    """Create the full customer support graph.

    The default graph uses a SQL database specialist and a documentation
    specialist behind a supervisor, with identity verification in front of
    account- and order-specific requests.
    """
    if database_agent is None:
        database_agent = create_sql_agent(use_checkpointer=use_checkpointer)

    if docs_agent is None:
        docs_agent = create_docs_agent(use_checkpointer=use_checkpointer)

    supervisor_agent = create_supervisor_agent(
        database_agent=database_agent,
        docs_agent=docs_agent,
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
            checkpointer=MemorySaver(), name="customer_support_agent"
        )
    return workflow.compile(name="customer_support_agent")
