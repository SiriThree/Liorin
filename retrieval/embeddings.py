"""Embedding provider factory and version/dimension contract."""

from __future__ import annotations

from dataclasses import dataclass
import os

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_openai import OpenAIEmbeddings


@dataclass(frozen=True)
class EmbeddingSpec:
    provider: str
    model_version: str
    dimension: int


EMBEDDING_SPECS = {
    "openai": EmbeddingSpec("openai", os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"), 1536),
    "huggingface": EmbeddingSpec(
        "huggingface",
        os.getenv("HF_EMBEDDING_MODEL", "sentence-transformers/all-mpnet-base-v2"),
        768,
    ),
}


def get_embedding_spec(provider: str = "huggingface") -> EmbeddingSpec:
    try:
        return EMBEDDING_SPECS[provider]
    except KeyError as exc:
        raise ValueError(f"Unsupported embedding provider: {provider}") from exc


def get_embeddings(provider: str = "huggingface"):
    spec = get_embedding_spec(provider)
    if provider == "openai":
        return OpenAIEmbeddings(model=spec.model_version)
    if provider == "huggingface":
        return HuggingFaceEmbeddings(model_name=spec.model_version)
    raise ValueError(f"Unsupported embedding provider: {provider}")
