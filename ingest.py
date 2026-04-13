import json
import os
from datetime import datetime
from pathlib import Path
from typing import Iterable, List

from dotenv import load_dotenv
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import CharacterTextSplitter

try:
    from markitdown import MarkItDown
except ImportError:  # Optional dependency for richer ingestion.
    MarkItDown = None


def _load_environment() -> None:
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    workspace_dir = os.path.dirname(repo_dir)
    env_candidates = [
        os.path.join(repo_dir, ".env"),
        os.path.join(workspace_dir, ".env.global"),
    ]
    for env_file in env_candidates:
        if os.path.exists(env_file):
            load_dotenv(env_file, override=False)


_load_environment()


def _iter_files(knowledge_dir: Path) -> Iterable[Path]:
    for path in knowledge_dir.rglob("*"):
        if path.is_file():
            yield path


def _load_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _convert_with_markitdown(converter: MarkItDown, path: Path) -> str:
    result = converter.convert(str(path))
    return result.text_content or ""


def _load_documents(knowledge_dir: Path) -> List[Document]:
    documents: List[Document] = []
    converter = MarkItDown(enable_plugins=False) if MarkItDown else None

    for path in _iter_files(knowledge_dir):
        text = ""
        if path.suffix.lower() in {".txt", ".md"}:
            text = _load_text_file(path)
        elif converter is not None:
            try:
                text = _convert_with_markitdown(converter, path)
            except Exception as exc:
                print(f"MarkItDown failed for {path}: {exc}")
                continue
        else:
            print(f"Skipping {path} (markitdown not installed).")
            continue

        if not text.strip():
            continue

        documents.append(
            Document(
                page_content=text,
                metadata={"source": str(path), "ext": path.suffix.lower()},
            )
        )

    return documents


def _write_meta(index_path: Path, doc_count: int) -> None:
    meta = {
        "indexed_at": datetime.utcnow().isoformat() + "Z",
        "documents": doc_count,
    }
    index_path.mkdir(parents=True, exist_ok=True)
    (index_path / ".ingest_meta.json").write_text(
        json.dumps(meta, indent=2),
        encoding="utf-8",
    )


def build_index(knowledge_dir: Path, index_path: Path) -> int:
    print(f"Starting local indexing from {knowledge_dir}...")

    documents = _load_documents(knowledge_dir)

    if not documents:
        print("No documents found for indexing.")
        return 0

    text_splitter = CharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    docs = text_splitter.split_documents(documents)

    embeddings = HuggingFaceEmbeddings(
        model_name="sentence-transformers/all-MiniLM-L6-v2"
    )
    vectorstore = FAISS.from_documents(docs, embeddings)
    vectorstore.save_local(str(index_path))
    _write_meta(index_path, len(docs))

    print(f"Indexed {len(docs)} knowledge chunks locally.")
    return len(docs)


def ingest_documents():
    knowledge_dir = Path("knowledge_base")
    index_path = Path("faiss_index")

    build_index(knowledge_dir, index_path)


if __name__ == "__main__":
    ingest_documents()
