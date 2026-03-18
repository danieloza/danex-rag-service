from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import os
from langchain_community.utilities import SQLDatabase
from langchain_core.prompts import PromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_classic.chains import create_sql_query_chain
from langchain_community.vectorstores import FAISS
from langchain_classic.chains import RetrievalQA
from dotenv import load_dotenv
import logging
from pdf_generator import create_pdf_report

# Load global configuration
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env.global"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Danex Global FREE RAG", version="0.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SALONOS_DB_PATH = os.path.join(BASE_DIR, "_cifix_DANIELOZAHUB3_01", "salonos.db")
DANEX_DB_PATH = os.path.join(BASE_DIR, "danex-business-api", "danex.db")
FAISS_INDEX_PATH = "faiss_index"

# Używamy darmowego modelu Gemini (wymaga klucza GOOGLE_API_KEY w .env.global)
# Darmowy limit to ok 15 zapytań na minutę.
FREE_LLM_MODEL = "gemini-2.0-flash"

class QueryRequest(BaseModel):
    question: str = ""
    query: str = "" # Compatibility with DanexRAGClient
    db_target: str = "salonos"

def get_hybrid_answer(question: str, db_target: str):
    # ... (rest of the function same as before)
    google_api_key = os.environ.get("GOOGLE_API_KEY")
    if not google_api_key:
        return "⚠️ Brak darmowego klucza GOOGLE_API_KEY w pliku .env.global. Możesz go dostać za darmo na aistudio.google.com"

    llm = ChatGoogleGenerativeAI(model=FREE_LLM_MODEL, google_api_key=google_api_key)
    
    # 1. Local Free Embeddings
    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    
    vector_answer = ""
    if os.path.exists(FAISS_INDEX_PATH):
        vectorstore = FAISS.load_local(FAISS_INDEX_PATH, embeddings, allow_dangerous_deserialization=True)
        qa_chain = RetrievalQA.from_chain_type(llm=llm, chain_type="stuff", retriever=vectorstore.as_retriever())
        vector_res = qa_chain.invoke(question)
        vector_answer = vector_res["result"]

    # 2. SQL Data
    sql_answer = ""
    keywords = ["ile", "utarg", "rezerwac", "wizyt", "faktur", "sum", "kto", "kiedy", "pokaż", "lista"]
    if any(k in question.lower() for k in keywords):
        db_path = SALONOS_DB_PATH if db_target == "salonos" else DANEX_DB_PATH
        db = SQLDatabase.from_uri(f"sqlite:///{db_path}")
        
        # Generowanie SQL przez Gemini
        sql_chain = create_sql_query_chain(llm, db)
        sql_query = sql_chain.invoke({"question": question})
        # Oczyszczanie query z formatowania markdown jeśli gemini je doda
        sql_query = sql_query.replace("```sql", "").replace("```", "").strip()
        
        sql_res = db.run(sql_query)
        
        final_prompt = PromptTemplate.from_template(
            "Pytanie: {question}\nSQL Result: {result}\nOdpowiedz konkretnie na podstawie tych danych:"
        )
        final_chain = final_prompt | llm
        sql_answer = final_chain.invoke({"question": question, "result": sql_res}).content

    if sql_answer and vector_answer and "nie wiem" not in vector_answer.lower():
        return f"Dane z systemu: {sql_answer}\n\nZgodnie z procedurami: {vector_answer}"
    return sql_answer or vector_answer or "Nie znalazłem danych w systemie ani w regulaminie."

@app.post("/api/v1/ask")
@app.post("/api/v1/query") # Compatibility with DanexRAGClient
async def ask_assistant(query: QueryRequest):
    try:
        q_text = query.question or query.query
        if not q_text:
            raise HTTPException(status_code=400, detail="Empty question/query")
            
        answer = get_hybrid_answer(q_text, query.db_target)
        return {"answer": answer, "sources": ["SQLite Local", "HuggingFace Local"], "confidence_score": 0.95}
    except Exception as e:
        logger.error(f"RAG Error: {e}")
        return {"answer": f"Wystąpił błąd techniczny: {str(e)}", "sources": [], "confidence_score": 0}

@app.post("/api/v1/report/pdf")
async def generate_pdf(req: dict):
    filename = f"raport_{os.urandom(4).hex()}.pdf"
    create_pdf_report(filename, req.get("title", "Raport"), req.get("content", ""))
    return {"status": "success", "download_url": f"http://localhost:8002/api/v1/report/download/{filename}"}

@app.get("/api/v1/report/download/{filename}")
async def download_pdf(filename: str):
    return FileResponse(os.path.join("reports", filename), media_type='application/pdf', filename=filename)

@app.get("/health")
async def health():
    return {"status": "ok", "free_mode": True, "local_embeddings": True}
