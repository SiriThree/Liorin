"""Configuration for the Liorin customer support agent."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# ============================================================================
# MODEL CONFIGURATION
# ============================================================================

# Primary model used by all agents.
# Set LIORIN_MODEL in .env to change the model.
# Examples:
#   - "anthropic:claude-haiku-4-5" (fast, cost-effective)
#   - "anthropic:claude-sonnet-4" (balanced)
#   - "openai:gpt-5-mini" (fast, OpenAI)
#   - "openai:gpt-5-nano" (lightweight, OpenAI)
DEFAULT_MODEL = os.getenv("LIORIN_MODEL", "anthropic:claude-haiku-4-5")

# ============================================================================
# EMBEDDING CONFIGURATION
# ============================================================================

# Embedding provider for document vectorstore
# Options: "huggingface" (local, no API key) or "openai" (requires OPENAI_API_KEY)
# Default is HuggingFace for backwards compatibility and no external dependencies
DEFAULT_EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "huggingface")

# ============================================================================
# RUNTIME CONFIGURATION
# ============================================================================


@dataclass
class Context:
    """Runtime configuration for all agents.

    This enables model selection in LangSmith Studio's configurable Assistants UI.
    """

    model: Literal[
        "anthropic:claude-haiku-4-5",
        "anthropic:claude-sonnet-4-5",
        "openai:gpt-5-mini",
        "openai:gpt-5-nano",
    ] = DEFAULT_MODEL


# ============================================================================
# DATA PATHS CONFIGURATION
# ============================================================================

# Determine the base path (works in both local dev and LS deployment environments)
if Path("/deps/liorin").exists():
    BASE_PATH = Path("/deps/liorin")
else:
    BASE_PATH = Path(__file__).parent

DEFAULT_DB_PATH = BASE_PATH / "data" / "structured" / "techhub.db"
DEFAULT_VECTORSTORE_PATH = (
    BASE_PATH
    / "data"
    / "vector_stores"
    / f"techhub_vectorstore_{DEFAULT_EMBEDDING_PROVIDER}.pkl"
)

# ============================================================================
# DEPLOYMENT CONFIGURATION
# ============================================================================

# LangGraph deployment URL (optional, used by simulation system)
# Set LANGGRAPH_DEPLOYMENT_URL in .env when running simulations against deployed graphs
DEFAULT_DEPLOYMENT_URL = os.getenv("LANGGRAPH_DEPLOYMENT_URL")
