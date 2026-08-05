"""Configuration for the Liorin customer support agent."""

import os
from dataclasses import dataclass
from pathlib import Path

# ============================================================================
# MODEL CONFIGURATION
# ============================================================================

# Primary model used by all agents.
# Set LIORIN_MODEL in .env to change the model.
# Examples:
#   - "openai:deepseek-chat" with OPENAI_BASE_URL="https://api.deepseek.com"
#   - "openai:qwen-plus" with a compatible DashScope endpoint
#   - "openai:glm-4-flash" with a compatible Zhipu endpoint
DEFAULT_MODEL = os.getenv("LIORIN_MODEL", "openai:deepseek-chat")

# ============================================================================
# EMBEDDING CONFIGURATION
# ============================================================================

# Embedding provider for document retrieval
# Options: "huggingface" (local, no API key) or "openai" (requires OPENAI_API_KEY)
# Default is HuggingFace for backwards compatibility and no external dependencies
DEFAULT_EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "huggingface")

# Milvus vector database configuration.
# Use a local/server Milvus URI such as "http://localhost:19530".
DEFAULT_MILVUS_URI = os.getenv("MILVUS_URI", "http://localhost:19530")
DEFAULT_MILVUS_TOKEN = os.getenv("MILVUS_TOKEN") or None
DEFAULT_MILVUS_COLLECTION = os.getenv(
    "MILVUS_COLLECTION",
    f"liorin_documents_{DEFAULT_EMBEDDING_PROVIDER}",
)


def get_milvus_connection_args() -> dict:
    """Return connection arguments for the LangChain Milvus vector store."""
    connection_args = {"uri": DEFAULT_MILVUS_URI}
    if DEFAULT_MILVUS_TOKEN:
        connection_args["token"] = DEFAULT_MILVUS_TOKEN
    return connection_args

# ============================================================================
# RUNTIME CONFIGURATION
# ============================================================================


@dataclass
class Context:
    """Runtime configuration for all agents.

    Use provider-prefixed model names such as "openai:deepseek-chat".
    """

    model: str = DEFAULT_MODEL


# ============================================================================
# DATA PATHS CONFIGURATION
# ============================================================================

# Determine the base path (works in both local dev and LS deployment environments)
if Path("/deps/liorin").exists():
    BASE_PATH = Path("/deps/liorin")
else:
    BASE_PATH = Path(__file__).parent

DEFAULT_DB_PATH = BASE_PATH / "data" / "structured" / "liorin.db"
DEFAULT_INDEX_REGISTRY_PATH = BASE_PATH / "data" / "index_registry.json"
# ============================================================================
# DEPLOYMENT CONFIGURATION
# ============================================================================

# LangGraph deployment URL (optional, used by simulation system)
# Set LANGGRAPH_DEPLOYMENT_URL in .env when running simulations against deployed graphs
DEFAULT_DEPLOYMENT_URL = os.getenv("LANGGRAPH_DEPLOYMENT_URL")
