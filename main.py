import json
import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from langchain_community.utilities import SQLDatabase
from langchain_community.vectorstores import FAISS
from langchain_classic.chains import RetrievalQA, create_sql_query_chain
from langchain_core.prompts import PromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_huggingface import HuggingFaceEmbeddings
from pydantic import BaseModel

from ingest import build_index
from pdf_generator import create_pdf_report


def _load_environment() -> None:
    """Prefer a local repo .env, then fall back to the shared workspace file."""
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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Danex Global Hybrid RAG", version="0.4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SALONOS_DB_PATH = os.environ.get(
    "SALONOS_DB_PATH",
    os.path.join(BASE_DIR, "_cifix_DANIELOZAHUB3_01", "salonos.db"),
)
DANEX_DB_PATH = os.environ.get(
    "DANEX_DB_PATH",
    os.path.join(BASE_DIR, "danex-business-api", "danex.db"),
)
KNOWLEDGE_DIR = Path("knowledge_base")
FAISS_INDEX_PATH = Path("faiss_index")
FREE_LLM_MODEL = "gemini-2.0-flash"
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
SESSION_CONTEXT: dict[str, list[str]] = {}

if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class QueryRequest(BaseModel):
    question: str = ""
    query: str = ""  # Compatibility with DanexRAGClient
    db_target: str = "salonos"
    session_id: str = ""
    context: list[str] | None = None


def _build_context(session_id: str, incoming: list[str] | None) -> str:
    history = SESSION_CONTEXT.get(session_id, [])
    merged = history + (incoming or [])
    merged = merged[-4:]
    if not merged:
        return ""
    return "\n".join(merged)


def _store_context(session_id: str, question: str, answer: str) -> None:
    if not session_id:
        return
    history = SESSION_CONTEXT.get(session_id, [])
    history.append(f"Q: {question}")
    history.append(f"A: {answer}")
    SESSION_CONTEXT[session_id] = history[-6:]


def _safe_snippet(text: str, limit: int = 280) -> str:
    cleaned = " ".join(text.split())
    return cleaned[:limit].strip()


def get_hybrid_answer(question: str, db_target: str, session_id: str, extra_ctx: list[str] | None):
    context_block = _build_context(session_id, extra_ctx)
    full_question = question if not context_block else f"{context_block}\n\nPytanie: {question}"

    google_api_key = os.environ.get("GOOGLE_API_KEY")
    if not google_api_key:
        return (
            "Missing GOOGLE_API_KEY. Add it to the local .env file "
            "or the shared workspace .env.global.",
            False,
            False,
            [],
            "none",
        )

    llm = ChatGoogleGenerativeAI(model=FREE_LLM_MODEL, google_api_key=google_api_key)
    embeddings = HuggingFaceEmbeddings(
        model_name="sentence-transformers/all-MiniLM-L6-v2"
    )

    vector_answer = ""
    vector_docs = []
    if FAISS_INDEX_PATH.exists():
        vectorstore = FAISS.load_local(
            str(FAISS_INDEX_PATH),
            embeddings,
            allow_dangerous_deserialization=True,
        )
        vector_docs = vectorstore.similarity_search(full_question, k=3)
        qa_chain = RetrievalQA.from_chain_type(
            llm=llm,
            chain_type="stuff",
            retriever=vectorstore.as_retriever(),
        )
        vector_res = qa_chain.invoke(full_question)
        vector_answer = vector_res["result"]
    used_vector = bool(vector_answer)

    sql_answer = ""
    keywords = ["ile", "utarg", "rezerwac", "wizyt", "faktur", "sum", "kto", "kiedy", "pokaz", "lista"]
    if any(keyword in question.lower() for keyword in keywords):
        db_path = SALONOS_DB_PATH if db_target == "salonos" else DANEX_DB_PATH
        db = SQLDatabase.from_uri(f"sqlite:///{db_path}")

        sql_chain = create_sql_query_chain(llm, db)
        sql_query = sql_chain.invoke({"question": full_question})
        sql_query = sql_query.replace("```sql", "").replace("```", "").strip()

        sql_res = db.run(sql_query)
        final_prompt = PromptTemplate.from_template(
            "Pytanie: {question}\nSQL Result: {result}\n"
            "Odpowiedz konkretnie na podstawie tych danych:"
        )
        final_chain = final_prompt | llm
        sql_answer = final_chain.invoke(
            {"question": full_question, "result": sql_res}
        ).content
    used_sql = bool(sql_answer)

    if sql_answer and vector_answer and "nie wiem" not in vector_answer.lower():
        citations = [
            {"source": doc.metadata.get("source", "unknown"), "snippet": _safe_snippet(doc.page_content)}
            for doc in vector_docs
        ]
        return (
            f"Dane z systemu: {sql_answer}\n\nZgodnie z procedurami: {vector_answer}",
            used_vector,
            used_sql,
            citations,
            "hybrid",
        )
    if used_sql and (not used_vector or "nie wiem" in vector_answer.lower()):
        return (
            sql_answer,
            used_vector,
            used_sql,
            [],
            "sql",
        )
    if used_vector:
        citations = [
            {"source": doc.metadata.get("source", "unknown"), "snippet": _safe_snippet(doc.page_content)}
            for doc in vector_docs
        ]
        return (
            vector_answer,
            used_vector,
            used_sql,
            citations,
            "vector",
        )
    return (
        "Nie znalazlem danych w systemie ani w regulaminie.",
        used_vector,
        used_sql,
        [],
        "none",
    )


@app.post("/api/v1/ask")
@app.post("/api/v1/query")  # Compatibility with DanexRAGClient
async def ask_assistant(query: QueryRequest):
    try:
        start = time.perf_counter()
        q_text = query.question or query.query
        if not q_text:
            raise HTTPException(status_code=400, detail="Empty question/query")

        answer, used_vector, used_sql, citations, route = get_hybrid_answer(
            q_text,
            query.db_target,
            query.session_id,
            query.context,
        )
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        sources = []
        if used_sql:
            sources.append("SQLite Local")
        if used_vector:
            sources.append("HuggingFace Local")
        _store_context(query.session_id, q_text, answer)
        return {
            "answer": answer,
            "sources": sources,
            "citations": citations,
            "confidence_score": 0.95,
            "meta": {
                "db_target": query.db_target,
                "used_vector": used_vector,
                "used_sql": used_sql,
                "model": FREE_LLM_MODEL,
                "latency_ms": latency_ms,
                "route": route,
            },
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("RAG error: %s", exc)
        return {
            "answer": f"Wystapil blad techniczny: {exc}",
            "sources": [],
            "confidence_score": 0,
        }


@app.post("/api/v1/report/pdf")
async def generate_pdf(req: dict):
    filename = f"raport_{os.urandom(4).hex()}.pdf"
    create_pdf_report(filename, req.get("title", "Raport"), req.get("content", ""))
    return {
        "status": "success",
        "download_url": f"http://localhost:8002/api/v1/report/download/{filename}",
    }


@app.get("/api/v1/report/download/{filename}")
async def download_pdf(filename: str):
    return FileResponse(
        os.path.join("reports", filename),
        media_type="application/pdf",
        filename=filename,
    )


@app.get("/")
async def root():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"status": "ok"}


@app.post("/api/v1/ingest/upload")
async def upload_documents(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    rebuild: bool = True,
):
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    saved = []
    for file in files:
        target = KNOWLEDGE_DIR / file.filename
        content = await file.read()
        target.write_bytes(content)
        saved.append(file.filename)
    if rebuild:
        background_tasks.add_task(build_index, KNOWLEDGE_DIR, FAISS_INDEX_PATH)
    return {"status": "ok", "saved": saved, "rebuild": rebuild}


@app.post("/api/v1/ingest/rebuild")
async def rebuild_index(background_tasks: BackgroundTasks):
    background_tasks.add_task(build_index, KNOWLEDGE_DIR, FAISS_INDEX_PATH)
    return {"status": "ok", "message": "Rebuild started"}


@app.get("/api/v1/debug/index")
async def index_status():
    meta_path = FAISS_INDEX_PATH / ".ingest_meta.json"
    meta = {}
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return {
        "index_path": str(FAISS_INDEX_PATH),
        "exists": FAISS_INDEX_PATH.exists(),
        "meta": meta,
    }


@app.get("/api/v1/debug/db")
async def db_status():
    def _stat(path: str) -> dict:
        return {
            "path": path,
            "exists": os.path.exists(path),
            "size": os.path.getsize(path) if os.path.exists(path) else 0,
        }

    return {
        "salonos": _stat(SALONOS_DB_PATH),
        "danex": _stat(DANEX_DB_PATH),
    }

@app.get("/health")
async def health():
    return {"status": "ok", "free_mode": True, "local_embeddings": True}
