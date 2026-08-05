"""用于检索 Liorin 产品手册和售后政策的文档工具。"""

from langchain_core.documents import Document
from langchain_core.tools import tool

from config import DEFAULT_INDEX_REGISTRY_PATH, DEFAULT_MILVUS_COLLECTION, get_milvus_connection_args
from config import DEFAULT_EMBEDDING_PROVIDER
from retrieval.embeddings import get_embedding_spec, get_embeddings
from retrieval.index_lifecycle import IndexLifecycleManager
from retrieval.document_corpus import CORPUS_SCHEMA_VERSION

# Cached vectorstore and retrievers (lazy loaded)
_vectorstore = None
_manual_retriever = None
_policy_retriever = None


def get_vectorstore():
    """懒加载连接 Milvus 向量数据库。"""
    global _vectorstore
    if _vectorstore is None:
        from langchain_milvus import Milvus

        spec = get_embedding_spec(DEFAULT_EMBEDDING_PROVIDER)
        manager = IndexLifecycleManager(DEFAULT_INDEX_REGISTRY_PATH)
        manifest = manager.active_manifest()
        collection_name = DEFAULT_MILVUS_COLLECTION
        if manifest is not None:
            if not manifest.compatible_with(
                embedding_model_version=spec.model_version,
                embedding_dimension=spec.dimension,
                metadata_schema_version=CORPUS_SCHEMA_VERSION,
            ):
                raise RuntimeError("active index is incompatible with configured embedding contract")
            collection_name = manifest.collection_name
        _vectorstore = Milvus(
            embedding_function=get_embeddings(DEFAULT_EMBEDDING_PROVIDER),
            collection_name=collection_name,
            connection_args=get_milvus_connection_args(),
            enable_dynamic_field=True,
        )

    return _vectorstore


def get_manual_retriever():
    """懒加载产品手册检索器。"""
    global _manual_retriever
    if _manual_retriever is None:
        vectorstore = get_vectorstore()
        _manual_retriever = vectorstore.as_retriever(
            search_type="similarity",
            search_kwargs={
                "k": 3,
                "expr": 'doc_type == "manual"',
            },
        )
    return _manual_retriever


def get_policy_retriever():
    """懒加载售后政策检索器。"""
    global _policy_retriever
    if _policy_retriever is None:
        vectorstore = get_vectorstore()
        _policy_retriever = vectorstore.as_retriever(
            search_type="similarity",
            search_kwargs={
                "k": 2,
                "expr": 'doc_type == "policy"',
            },
        )
    return _policy_retriever


@tool(response_format="content_and_artifact")
def search_manuals(query: str) -> tuple[str, list[Document]]:
    """Deprecated unauthenticated tool surface.

    Stage 4 deliberately refuses direct retrieval without a request principal.  The
    production Knowledge Agent uses ``hybrid_retrieve`` where ACL is mandatory.
    """
    return "该兼容工具缺少授权 Principal，已按默认拒绝策略阻止检索。", []


@tool(response_format="content_and_artifact")
def search_support_policies(query: str) -> tuple[str, list[Document]]:
    """Deprecated unauthenticated policy tool; use the production Knowledge Agent."""
    return "该兼容工具缺少授权 Principal，已按默认拒绝策略阻止检索。", []


def clear_vectorstore_cache() -> None:
    global _vectorstore, _manual_retriever, _policy_retriever
    _vectorstore = None
    _manual_retriever = None
    _policy_retriever = None
