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

# Maximum provider-neutral token estimate allocated to dynamic runtime context.
# This excludes the fixed system prompt/tool schemas and is enforced again at
# the model-call boundary for the active turn.
DEFAULT_CONTEXT_MAX_TOKENS = int(os.getenv("LIORIN_CONTEXT_MAX_TOKENS", "4096"))


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().casefold() in {"1", "true", "yes", "on"}


# Context compaction is evaluated before selector/budget at the supervisor
# model-call boundary. These values are runtime defaults and can be overridden
# through the LangGraph Context dataclass.
DEFAULT_CONTEXT_COMPACTION_ENABLED = _env_bool(
    "LIORIN_CONTEXT_COMPACTION_ENABLED", True
)
DEFAULT_CONTEXT_COMPACTION_ITEM_THRESHOLD = int(
    os.getenv("LIORIN_CONTEXT_COMPACTION_ITEM_THRESHOLD", "24")
)
DEFAULT_CONTEXT_COMPACTION_RECENT_MESSAGES = int(
    os.getenv("LIORIN_CONTEXT_COMPACTION_RECENT_MESSAGES", "6")
)
DEFAULT_CONTEXT_COMPACTION_SUMMARY_MAX_TOKENS = int(
    os.getenv("LIORIN_CONTEXT_COMPACTION_SUMMARY_MAX_TOKENS", "512")
)

# Phase 5 long-term MemoryFact retrieval. The default backend is process-local;
# these settings only govern Context Runtime retrieval and injection.
DEFAULT_LONG_TERM_MEMORY_ENABLED = _env_bool(
    "LIORIN_LONG_TERM_MEMORY_ENABLED", True
)
DEFAULT_LONG_TERM_MEMORY_RETRIEVAL_LIMIT = int(
    os.getenv("LIORIN_LONG_TERM_MEMORY_RETRIEVAL_LIMIT", "6")
)

# Production reliability defaults for external/sub-agent calls.
DEFAULT_TOOL_TIMEOUT_SECONDS = float(os.getenv("LIORIN_TOOL_TIMEOUT_SECONDS", "30"))
DEFAULT_TOOL_RETRY_ATTEMPTS = int(os.getenv("LIORIN_TOOL_RETRY_ATTEMPTS", "2"))

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
    context_max_tokens: int = DEFAULT_CONTEXT_MAX_TOKENS
    context_compaction_enabled: bool = DEFAULT_CONTEXT_COMPACTION_ENABLED
    context_compaction_item_threshold: int = DEFAULT_CONTEXT_COMPACTION_ITEM_THRESHOLD
    context_compaction_recent_messages: int = DEFAULT_CONTEXT_COMPACTION_RECENT_MESSAGES
    context_compaction_summary_max_tokens: int = DEFAULT_CONTEXT_COMPACTION_SUMMARY_MAX_TOKENS
    long_term_memory_enabled: bool = DEFAULT_LONG_TERM_MEMORY_ENABLED
    long_term_memory_retrieval_limit: int = DEFAULT_LONG_TERM_MEMORY_RETRIEVAL_LIMIT

    def __post_init__(self) -> None:
        if self.context_max_tokens <= 0:
            raise ValueError("context_max_tokens must be greater than zero")
        if self.context_compaction_item_threshold <= 0:
            raise ValueError("context_compaction_item_threshold must be greater than zero")
        if self.context_compaction_recent_messages < 0:
            raise ValueError("context_compaction_recent_messages must not be negative")
        if self.context_compaction_summary_max_tokens <= 0:
            raise ValueError("context_compaction_summary_max_tokens must be greater than zero")
        if self.long_term_memory_retrieval_limit <= 0:
            raise ValueError("long_term_memory_retrieval_limit must be greater than zero")


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
