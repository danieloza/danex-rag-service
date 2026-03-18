import os

from dotenv import load_dotenv
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import CharacterTextSplitter


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


def ingest_documents():
    knowledge_dir = "knowledge_base"
    index_path = "faiss_index"

    print(f"Starting local indexing from {knowledge_dir}...")

    loader = DirectoryLoader(
        knowledge_dir,
        glob="**/*.txt",
        loader_cls=TextLoader,
        loader_kwargs={"encoding": "utf-8"},
    )
    documents = loader.load()

    if not documents:
        print("No documents found for indexing.")
        return

    text_splitter = CharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    docs = text_splitter.split_documents(documents)

    embeddings = HuggingFaceEmbeddings(
        model_name="sentence-transformers/all-MiniLM-L6-v2"
    )
    vectorstore = FAISS.from_documents(docs, embeddings)
    vectorstore.save_local(index_path)

    print(f"Indexed {len(docs)} knowledge chunks locally.")


if __name__ == "__main__":
    ingest_documents()
