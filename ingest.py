import os
from langchain_community.document_loaders import TextLoader, DirectoryLoader
from langchain_text_splitters import CharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from dotenv import load_dotenv

# Load global config
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env.global"))

def ingest_documents():
    knowledge_dir = "knowledge_base"
    index_path = "faiss_index"
    
    print(f"📥 Rozpoczynam darmowe indeksowanie lokalne z {knowledge_dir}...")
    
    # 1. Load Documents
    loader = DirectoryLoader(knowledge_dir, glob="**/*.txt", loader_cls=TextLoader, loader_kwargs={'encoding': 'utf-8'})
    documents = loader.load()
    
    if not documents:
        print("⚠️ Brak dokumentów do zaindeksowania.")
        return

    # 2. Split text into chunks
    text_splitter = CharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    docs = text_splitter.split_documents(documents)
    
    # 3. Create Embeddings (Local & Free) and Save to FAISS
    # Ten model zostanie pobrany raz (ok 80MB) i działa lokalnie na CPU
    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    vectorstore = FAISS.from_documents(docs, embeddings)
    vectorstore.save_local(index_path)
    
    print(f"✅ Sukces! Zaindeksowano {len(docs)} fragmentów wiedzy lokalnie (0 PLN).")

if __name__ == "__main__":
    ingest_documents()
