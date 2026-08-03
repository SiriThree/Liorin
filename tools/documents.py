"""
Documents tools for searching Liorin product manuals and support policies.

These tools provide semantic search over:
- Product manuals from the TraceMind dataset (setup, usage, troubleshooting)
- Support policies (returns, warranties, shipping, repair intake, refunds)

The vectorstore is pre-built from markdown documents and uses:
- Configurable embeddings (HuggingFace by default, or OpenAI)
- InMemoryVectorStore for fast retrieval
- VectorStoreRetriever for proper tracing and Runnable interface
- Metadata filtering to separate manuals from policies

Tools use response_format="content_and_artifact" to return both:
- Formatted content string for the LLM
- Raw Document objects as artifacts for downstream processing and LangSmith tracing
"""

import pickle

from langchain_core.documents import Document
from langchain_core.tools import tool
from langchain_core.vectorstores import InMemoryVectorStore

from config import DEFAULT_VECTORSTORE_PATH

# Cached vectorstore and retrievers (lazy loaded)
_vectorstore = None
_manual_retriever = None
_policy_retriever = None


def get_vectorstore():
    """Lazy load the vectorstore.

    Creates the vectorstore on first call, then returns the cached instance
    for all subsequent calls. If the vectorstore doesn't exist, builds it automatically.

    Returns:
        InMemoryVectorStore: Cached vectorstore instance.
    """
    global _vectorstore
    if _vectorstore is None:
        if not DEFAULT_VECTORSTORE_PATH.exists():
            # Auto-build vectorstore if it doesn't exist
            print(
                f"Vectorstore not found at {DEFAULT_VECTORSTORE_PATH}. Building now..."
            )
            from data.data_generation.build_vectorstore import build_vectorstore

            build_vectorstore()

        with open(DEFAULT_VECTORSTORE_PATH, "rb") as f:
            data = pickle.load(f)

        # Handle both old format (direct vectorstore) and new format (dict with store + provider)
        if isinstance(data, dict) and "store" in data and "provider" in data:
            # New format: reconstruct vectorstore with embeddings
            from data.data_generation.build_vectorstore import get_embeddings

            embeddings = get_embeddings(data["provider"])
            _vectorstore = InMemoryVectorStore(embedding=embeddings)
            _vectorstore.store = data["store"]
        else:
            # Old format: direct vectorstore pickle (backwards compatibility)
            _vectorstore = data

    return _vectorstore


def get_manual_retriever():
    """Lazy load the product manual retriever.

    Creates the retriever on first call, then returns the cached instance
    for all subsequent calls.

    Returns:
        VectorStoreRetriever: Cached retriever for product manuals.
    """
    global _manual_retriever
    if _manual_retriever is None:
        vectorstore = get_vectorstore()
        _manual_retriever = vectorstore.as_retriever(
            search_type="similarity",
            search_kwargs={
                "k": 3,
                "filter": lambda doc: doc.metadata.get("doc_type") == "manual",
            },
        )
    return _manual_retriever


def get_policy_retriever():
    """Lazy load the policy documents retriever.

    Creates the retriever on first call, then returns the cached instance
    for all subsequent calls.

    Returns:
        VectorStoreRetriever: Cached retriever for policy documents.
    """
    global _policy_retriever
    if _policy_retriever is None:
        vectorstore = get_vectorstore()
        _policy_retriever = vectorstore.as_retriever(
            search_type="similarity",
            search_kwargs={
                "k": 2,
                "filter": lambda doc: doc.metadata.get("doc_type") == "policy",
            },
        )
    return _policy_retriever


@tool(response_format="content_and_artifact")
def search_manuals(query: str) -> tuple[str, list[Document]]:
    """Search product manuals for specifications, setup, usage, and troubleshooting.

    Use this tool when users ask about:
    - Product specifications
    - Features and capabilities
    - Setup and usage instructions
    - Troubleshooting symptoms and error handling
    - Safety notes and maintenance
    - Technical details
    - Product comparisons

    Args:
        query: What to search for (e.g., "air purifier filter reset", "hair dryer cold start")

    Returns:
        Tuple of (formatted_content, documents) where:
        - formatted_content: Clean string for the LLM with product info
        - documents: List of raw Document objects for downstream use and tracing
    """
    retriever = get_manual_retriever()

    # Use retriever to get documents (better tracing in LangSmith)
    results = retriever.invoke(query)

    if not results:
        return "No relevant product manual content found.", []

    # Format results with sources for the LLM
    formatted_results = []
    for doc in results:
        manual_name = doc.metadata.get("manual_name", "Unknown Manual")
        product_id = doc.metadata.get("product_id", "")
        formatted_results.append(f"[{manual_name} ({product_id})]\n{doc.page_content}")

    # Return tuple: (content for LLM, raw docs as artifact)
    return "\n\n---\n\n".join(formatted_results), results


@tool(response_format="content_and_artifact")
def search_support_policies(query: str) -> tuple[str, list[Document]]:
    """Search support policies including returns, warranties, repairs, refunds, and shipping.

    Use this tool when users ask about:
    - Return and refund policies
    - Warranty coverage and terms
    - Shipping information and timelines
    - Customer support policies
    - General store policies

    Args:
        query: What policy information to find (e.g., "return policy", "warranty coverage", "repair ticket")

    Returns:
        Tuple of (formatted_content, documents) where:
        - formatted_content: Clean string for the LLM with policy info
        - documents: List of raw Document objects for downstream use and tracing
    """
    retriever = get_policy_retriever()

    # Use retriever to get documents (better tracing in LangSmith)
    results = retriever.invoke(query)

    if not results:
        return "No relevant policy information found.", []

    # Format results with sources for the LLM
    formatted_results = []
    for doc in results:
        policy_name = doc.metadata.get("policy_name", "Unknown Policy")
        formatted_results.append(f"[{policy_name}]\n{doc.page_content}")

    # Return tuple: (content for LLM, raw docs as artifact)
    return "\n\n---\n\n".join(formatted_results), results
