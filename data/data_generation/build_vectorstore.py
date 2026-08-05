"""
Build the Liorin Milvus vector database from knowledge markdown files.

Milvus stores relatively stable unstructured knowledge: manuals, policies, and
FAQ documents. Frequently changing business records such as tickets and orders
are retrieved from SQLite/local corpus at runtime.
"""

from langchain_milvus import Milvus

from config import (
    DEFAULT_EMBEDDING_PROVIDER,
    DEFAULT_INDEX_REGISTRY_PATH,
    DEFAULT_MILVUS_COLLECTION,
    DEFAULT_MILVUS_URI,
    get_milvus_connection_args,
)
from retrieval.document_corpus import CORPUS_SCHEMA_VERSION, corpus_version, load_chunked_documents
from retrieval.embeddings import get_embedding_spec, get_embeddings
from retrieval.index_lifecycle import IndexLifecycleManager, IndexManifest, content_checksum


def build_vectorstore():
    """Build and save the Liorin stable knowledge collection in Milvus."""
    print("Building Liorin Milvus vectorstore")
    print("=" * 60)
    print(f"Embedding provider: {DEFAULT_EMBEDDING_PROVIDER}")
    print(f"Milvus URI: {DEFAULT_MILVUS_URI}")
    print(f"Milvus collection: {DEFAULT_MILVUS_COLLECTION}")

    spec = get_embedding_spec(DEFAULT_EMBEDDING_PROVIDER)
    embeddings = get_embeddings(DEFAULT_EMBEDDING_PROVIDER)
    docs = [
        doc
        for doc in load_chunked_documents()
        if doc.metadata.get("doc_type") in {"manual", "policy", "faq"}
    ]

    if not docs:
        raise RuntimeError("No manual, policy, or FAQ documents found under data/knowledge")

    for doc in docs:
        doc.metadata.pop("full_text", None)

    counts = {}
    for doc in docs:
        doc_type = doc.metadata.get("doc_type", "unknown")
        counts[doc_type] = counts.get(doc_type, 0) + 1

    print(f"Created chunks: {len(docs)}")
    for doc_type, count in sorted(counts.items()):
        print(f"{doc_type} chunks: {count}")

    checksum = content_checksum(
        [
            "|".join(
                [
                    str(doc.metadata.get("chunk_id") or ""),
                    str(doc.metadata.get("document_id") or ""),
                    str(doc.metadata.get("doc_type") or ""),
                    str(doc.metadata.get("version") or ""),
                    doc.page_content,
                ]
            )
            for doc in sorted(docs, key=lambda item: str(item.metadata.get("chunk_id") or ""))
        ]
    )
    manager = IndexLifecycleManager(DEFAULT_INDEX_REGISTRY_PATH)
    manifest = IndexManifest(
        corpus_version=corpus_version(),
        embedding_model_version=spec.model_version,
        embedding_dimension=spec.dimension,
        tokenizer_version="retrieval.sparse_retriever.tokenize",
        chunking_version="retrieval.document_corpus.CHUNK_SIZE=1000;CHUNK_OVERLAP=200",
        metadata_schema_version=CORPUS_SCHEMA_VERSION,
        collection_name=DEFAULT_MILVUS_COLLECTION,
        document_count=len({str(doc.metadata.get("document_id") or "") for doc in docs}),
        chunk_count=len(docs),
        checksum=checksum,
    )
    manager.register_build(manifest)
    try:
        Milvus.from_documents(
            documents=docs,
            embedding=embeddings,
            collection_name=DEFAULT_MILVUS_COLLECTION,
            connection_args=get_milvus_connection_args(),
            enable_dynamic_field=True,
            drop_old=True,
        )
    except Exception:
        manager.mark_failed(manifest.index_build_id)
        raise
    manager.mark_ready(manifest.index_build_id, checksum=checksum)
    manager.activate(manifest.index_build_id)

    print(f"Saved Milvus collection: {DEFAULT_MILVUS_COLLECTION}")
    print(f"Registered index manifest: {manifest.index_build_id}")
    print(f"Manifest registry: {DEFAULT_INDEX_REGISTRY_PATH}")
    return DEFAULT_MILVUS_COLLECTION


if __name__ == "__main__":
    build_vectorstore()
