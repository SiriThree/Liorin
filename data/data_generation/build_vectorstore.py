"""
Build the Liorin InMemoryVectorStore from TraceMind-derived knowledge files.

This script:
1. Loads product manuals and support policies from data/knowledge
2. Splits them into chunks with source metadata
3. Creates embeddings using the configured provider
4. Saves a compact vectorstore pickle for runtime retrieval
"""

import pickle
from pathlib import Path

from langchain_community.document_loaders import TextLoader
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import BASE_PATH, DEFAULT_EMBEDDING_PROVIDER, DEFAULT_VECTORSTORE_PATH


def get_embeddings(provider: str = "huggingface"):
    """Return embeddings for the configured provider."""
    if provider == "openai":
        return OpenAIEmbeddings(model="text-embedding-3-small")
    return HuggingFaceEmbeddings(model_name="sentence-transformers/all-mpnet-base-v2")


def _load_markdown_documents(directory: Path, doc_type: str) -> list:
    docs = []
    for md_file in sorted(directory.glob("*.md")):
        loaded = TextLoader(str(md_file), encoding="utf-8").load()
        for doc in loaded:
            doc.metadata["doc_type"] = doc_type
            doc.metadata["source_file"] = md_file.name

            if doc_type == "manual":
                stem = md_file.stem
                product_id, _, manual_name = stem.partition("_")
                doc.metadata["product_id"] = product_id
                doc.metadata["manual_name"] = manual_name or stem
            else:
                doc.metadata["policy_name"] = md_file.stem

        docs.extend(loaded)
    return docs


def build_vectorstore():
    """Build and save the Liorin vectorstore."""
    project_root = BASE_PATH
    manuals_dir = project_root / "data" / "knowledge" / "manuals"
    policies_dir = project_root / "data" / "knowledge" / "policies"

    print("Building Liorin vectorstore")
    print("=" * 60)
    print(f"Project root: {project_root}")
    print(f"Embedding provider: {DEFAULT_EMBEDDING_PROVIDER}")

    embeddings = get_embeddings(DEFAULT_EMBEDDING_PROVIDER)

    manual_docs = _load_markdown_documents(manuals_dir, "manual")
    policy_docs = _load_markdown_documents(policies_dir, "policy")
    all_docs = manual_docs + policy_docs

    if not all_docs:
        raise RuntimeError("No knowledge documents found under data/knowledge")

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        add_start_index=True,
    )
    splits = text_splitter.split_documents(all_docs)

    manual_chunks = [doc for doc in splits if doc.metadata["doc_type"] == "manual"]
    policy_chunks = [doc for doc in splits if doc.metadata["doc_type"] == "policy"]

    print(f"Loaded manuals: {len(manual_docs)}")
    print(f"Loaded policies: {len(policy_docs)}")
    print(f"Created chunks: {len(splits)}")
    print(f"Manual chunks: {len(manual_chunks)}")
    print(f"Policy chunks: {len(policy_chunks)}")

    vectorstore = InMemoryVectorStore.from_documents(
        documents=splits,
        embedding=embeddings,
    )

    output_path = DEFAULT_VECTORSTORE_PATH
    output_path.parent.mkdir(parents=True, exist_ok=True)

    vectorstore_data = {
        "store": vectorstore.store,
        "provider": DEFAULT_EMBEDDING_PROVIDER,
    }

    with open(output_path, "wb") as f:
        pickle.dump(vectorstore_data, f)

    print(f"Saved vectorstore: {output_path}")
    return output_path


if __name__ == "__main__":
    build_vectorstore()
