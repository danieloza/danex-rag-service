import json
import logging
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from langchain_community.utilities import SQLDatabase
from langchain_community.vectorstores import FAISS
from langchain_classic.chains import create_sql_query_chain
from langchain_core.prompts import PromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_huggingface import HuggingFaceEmbeddings
from pydantic import BaseModel, Field

from ingest import build_index
from pdf_generator import create_pdf_report
from retrieval_control import (
    activate_profile,
    compare_rankings,
    control_plane_summary,
    create_profile,
    evaluate_release_gate,
    get_active_profile,
    get_profile,
    get_replay,
    get_trace,
    initialize_control_plane,
    latest_replay_for_candidate,
    lexical_search,
    list_profile_events,
    list_profiles,
    list_replays,
    list_traces,
    rebuild_lexical_index,
    reciprocal_rank_fusion,
    save_replay,
    save_trace,
    utc_now,
)


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

app = FastAPI(title="Danex Global Hybrid RAG", version="1.0.0")

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
QUERY_HISTORY_PATH = Path(
    os.environ.get("DANEX_QUERY_HISTORY_PATH", ".runtime-query-history.json")
)
INGEST_HISTORY_PATH = KNOWLEDGE_DIR / ".ingest_history.json"
CONTROL_PLANE_DB_PATH = Path(
    os.environ.get("DANEX_CONTROL_PLANE_DB_PATH", ".runtime-control-plane.sqlite3")
)
GOLDEN_DATASET_PATH = Path("evals/golden_dataset.json")
_EMBEDDINGS_CACHE: HuggingFaceEmbeddings | None = None
_VECTORSTORE_CACHE: FAISS | None = None
_VECTORSTORE_SIGNATURE: tuple[float, float] | None = None

if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class QueryRequest(BaseModel):
    question: str = ""
    query: str = ""  # Compatibility with DanexRAGClient
    db_target: str = "salonos"
    session_id: str = ""
    context: list[str] | None = None
    synthesize: bool = True


class RetrievalSettings(BaseModel):
    lexical_weight: float = Field(default=1.0, ge=0, le=5)
    dense_weight: float = Field(default=1.0, ge=0, le=5)
    rank_constant: int = Field(default=60, ge=1, le=200)
    top_k: int = Field(default=5, ge=1, le=20)
    min_ndcg_delta: float = Field(default=-0.02, ge=-1, le=1)
    max_citation_churn: float = Field(default=0.55, ge=0, le=1)
    max_p95_latency_delta_ms: float = Field(default=250, ge=0, le=10000)


class ProfileCreateRequest(BaseModel):
    version: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,63}$")
    name: str = Field(min_length=3, max_length=120)
    description: str = Field(min_length=3, max_length=500)
    settings: RetrievalSettings
    actor: str = Field(default="portfolio-operator", min_length=2, max_length=80)


class ReplayQuery(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    expected_sources: list[str] = Field(default_factory=list)


class ReplayRequest(BaseModel):
    current_profile: str | None = None
    candidate_profile: str = "rag-2026.08-candidate"
    include_history: bool = True
    include_golden: bool = True
    include_dense: bool = True
    limit: int = Field(default=20, ge=1, le=100)
    queries: list[ReplayQuery] = Field(default_factory=list)


class ProfileActionRequest(BaseModel):
    actor: str = Field(default="portfolio-operator", min_length=2, max_length=80)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json_list(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _seed_ingestion_history_if_missing() -> None:
    if INGEST_HISTORY_PATH.exists() or not KNOWLEDGE_DIR.exists():
        return
    files = [path.name for path in KNOWLEDGE_DIR.iterdir() if path.is_file() and not path.name.startswith(".")]
    if not files:
        return
    _record_ingest_event("seed", files, False, "indexed")


def _write_json_list(path: Path, items: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, indent=2), encoding="utf-8")


def _append_json_item(path: Path, item: dict, limit: int = 50) -> None:
    items = _read_json_list(path)
    items.insert(0, item)
    _write_json_list(path, items[:limit])


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


def _record_query_history(
    query_id: str,
    question: str,
    answer: str,
    db_target: str,
    route: str,
    latency_ms: float,
    citations: list[dict],
    profile_version: str,
) -> None:
    _append_json_item(
        QUERY_HISTORY_PATH,
        {
            "query_id": query_id,
            "timestamp": _utc_now(),
            "question": question,
            "answer_preview": _safe_snippet(answer, 220),
            "db_target": db_target,
            "route": route,
            "latency_ms": latency_ms,
            "citations_count": len(citations),
            "top_score": citations[0]["score"] if citations else None,
            "citation_sources": [citation.get("source") for citation in citations],
            "retrieval_profile_version": profile_version,
        },
    )


def _record_ingest_event(action: str, filenames: list[str], rebuild: bool, status: str) -> None:
    _append_json_item(
        INGEST_HISTORY_PATH,
        {
            "timestamp": _utc_now(),
            "action": action,
            "files": filenames,
            "rebuild": rebuild,
            "status": status,
        },
    )


def _knowledge_file_entry(path: Path) -> dict:
    return {
        "name": path.name,
        "size": path.stat().st_size,
        "updated_at": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
    }


def _safe_snippet(text: str, limit: int = 280) -> str:
    cleaned = " ".join(text.split())
    return cleaned[:limit].strip()


def _normalize_scores(raw_scores: list[float]) -> list[float]:
    if not raw_scores:
        return []
    min_score = min(raw_scores)
    max_score = max(raw_scores)
    if max_score == min_score:
        return [1.0 for _ in raw_scores]
    return [(max_score - score) / (max_score - min_score) for score in raw_scores]


def _ensure_control_plane() -> None:
    initialize_control_plane(CONTROL_PLANE_DB_PATH, KNOWLEDGE_DIR)


def _index_signature() -> tuple[float, float] | None:
    faiss_file = FAISS_INDEX_PATH / "index.faiss"
    pickle_file = FAISS_INDEX_PATH / "index.pkl"
    if not faiss_file.exists() or not pickle_file.exists():
        return None
    return (faiss_file.stat().st_mtime, pickle_file.stat().st_mtime)


def _dense_search(question: str, limit: int = 12) -> list[dict[str, Any]]:
    global _EMBEDDINGS_CACHE, _VECTORSTORE_CACHE, _VECTORSTORE_SIGNATURE
    signature = _index_signature()
    if signature is None:
        return []
    if _EMBEDDINGS_CACHE is None:
        _EMBEDDINGS_CACHE = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2"
        )
    if _VECTORSTORE_CACHE is None or _VECTORSTORE_SIGNATURE != signature:
        _VECTORSTORE_CACHE = FAISS.load_local(
            str(FAISS_INDEX_PATH),
            _EMBEDDINGS_CACHE,
            allow_dangerous_deserialization=True,
        )
        _VECTORSTORE_SIGNATURE = signature
    scored = _VECTORSTORE_CACHE.similarity_search_with_score(question, k=limit)
    raw_scores = [score for _, score in scored]
    normalized = _normalize_scores(raw_scores)
    return [
        {
            "id": Path(doc.metadata.get("source", "unknown")).name.lower(),
            "source": Path(doc.metadata.get("source", "unknown")).name,
            "content": doc.page_content,
            "retrieval_score": round(score, 6),
        }
        for (doc, _), score in zip(scored, normalized)
    ]


def _retrieve_with_profile(
    question: str,
    profile: dict[str, Any],
    include_dense: bool = True,
    prepared_channels: tuple[list[dict[str, Any]], list[dict[str, Any]]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    _ensure_control_plane()
    stages = []
    if prepared_channels is None:
        lexical_started = time.perf_counter()
        lexical_results = lexical_search(CONTROL_PLANE_DB_PATH, question, limit=12)
        lexical_ms = round((time.perf_counter() - lexical_started) * 1000, 2)
        stages.append(
            {
                "id": "lexical",
                "label": "FTS5 lexical retrieval",
                "status": "complete",
                "duration_ms": lexical_ms,
                "candidates": len(lexical_results),
            }
        )

        dense_results: list[dict[str, Any]] = []
        dense_error = None
        dense_started = time.perf_counter()
        if include_dense:
            try:
                dense_results = _dense_search(question, limit=12)
            except Exception as exc:
                dense_error = str(exc)
                logger.warning("Dense retrieval unavailable: %s", exc)
        dense_ms = round((time.perf_counter() - dense_started) * 1000, 2)
        stages.append(
            {
                "id": "dense",
                "label": "FAISS dense retrieval",
                "status": "complete" if include_dense and not dense_error else "skipped",
                "duration_ms": dense_ms,
                "candidates": len(dense_results),
                "detail": dense_error or ("disabled" if not include_dense else None),
            }
        )
    else:
        lexical_results, dense_results = prepared_channels

    fusion_started = time.perf_counter()
    fused = reciprocal_rank_fusion(
        lexical_results,
        dense_results,
        profile["settings"],
    )
    fusion_ms = round((time.perf_counter() - fusion_started) * 1000, 2)
    stages.append(
        {
            "id": "fusion",
            "label": f"RRF fusion (k={profile['settings']['rank_constant']})",
            "status": "complete",
            "duration_ms": fusion_ms,
            "candidates": len(fused),
        }
    )
    return fused, {
        "profile_version": profile["version"],
        "channels": {
            "lexical": len(lexical_results),
            "dense": len(dense_results),
        },
        "settings": profile["settings"],
        "stages": stages,
    }


def _citations_from_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "source": result["source"],
            "snippet": _safe_snippet(result.get("content", "")),
            "score": result["score"],
            "rank": result["rank"],
            "channels": result["channels"],
            "channel_ranks": result["channel_ranks"],
            "contributions": result["contributions"],
        }
        for result in results
    ]


def get_hybrid_answer(
    question: str,
    db_target: str,
    session_id: str,
    extra_ctx: list[str] | None,
    synthesize: bool = True,
):
    context_block = _build_context(session_id, extra_ctx)
    full_question = question if not context_block else f"{context_block}\n\nPytanie: {question}"

    _ensure_control_plane()
    profile = get_active_profile(CONTROL_PLANE_DB_PATH)
    google_api_key = os.environ.get("GOOGLE_API_KEY")
    include_dense = bool(google_api_key) or os.environ.get("DANEX_ENABLE_LOCAL_EMBEDDINGS") == "1"
    retrieval_results, retrieval_plan = _retrieve_with_profile(
        full_question,
        profile,
        include_dense=include_dense,
    )
    citations = _citations_from_results(retrieval_results)

    if not google_api_key or not synthesize:
        reason = "Missing GOOGLE_API_KEY" if not google_api_key else "LLM synthesis disabled"
        retrieval_plan["synthesis_status"] = "skipped"
        return (
            f"{reason}. Retrieval completed in local evidence mode; "
            "inspect the ranked citations below or configure the key for answer synthesis.",
            any("dense" in result["channels"] for result in retrieval_results),
            False,
            citations,
            "retrieval_only" if citations else "none",
            retrieval_plan,
            profile["version"],
        )

    llm = ChatGoogleGenerativeAI(model=FREE_LLM_MODEL, google_api_key=google_api_key)
    vector_answer = ""
    if retrieval_results:
        evidence = "\n\n".join(
            f"[{result['source']}] {result['content']}"
            for result in retrieval_results
        )
        answer_prompt = PromptTemplate.from_template(
            "You are a source-bound enterprise assistant. Answer only from the evidence. "
            "If the evidence is insufficient, say that you do not know. "
            "Name the supporting source files in the answer.\n\n"
            "Question:\n{question}\n\nEvidence:\n{evidence}\n\nAnswer:"
        )
        vector_answer = (answer_prompt | llm).invoke(
            {"question": full_question, "evidence": evidence}
        ).content
    used_vector = any("dense" in result["channels"] for result in retrieval_results)
    used_retrieval = bool(retrieval_results)

    sql_answer = ""
    keywords = ["ile", "utarg", "rezerwac", "wizyt", "faktur", "sum", "kto", "kiedy", "pokaz", "lista"]
    if any(keyword in question.lower() for keyword in keywords):
        db_path = SALONOS_DB_PATH if db_target == "salonos" else DANEX_DB_PATH
        if os.path.exists(db_path):
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
    retrieval_plan["synthesis_status"] = "complete"

    if sql_answer and vector_answer and "nie wiem" not in vector_answer.lower():
        return (
            f"Dane z systemu: {sql_answer}\n\nZgodnie z procedurami: {vector_answer}",
            used_vector,
            used_sql,
            citations,
            "hybrid",
            retrieval_plan,
            profile["version"],
        )
    if used_sql and (not used_retrieval or "nie wiem" in vector_answer.lower()):
        return (
            sql_answer,
            used_vector,
            used_sql,
            [],
            "sql",
            retrieval_plan,
            profile["version"],
        )
    if used_retrieval:
        return (
            vector_answer,
            used_vector,
            used_sql,
            citations,
            "retrieval",
            retrieval_plan,
            profile["version"],
        )
    return (
        "Nie znalazlem danych w systemie ani w regulaminie.",
        used_vector,
        used_sql,
        [],
        "none",
        retrieval_plan,
        profile["version"],
    )


@app.post("/api/v1/ask")
@app.post("/api/v1/query")  # Compatibility with DanexRAGClient
async def ask_assistant(query: QueryRequest):
    try:
        start = time.perf_counter()
        query_id = f"qry_{uuid.uuid4().hex[:12]}"
        q_text = query.question or query.query
        if not q_text:
            raise HTTPException(status_code=400, detail="Empty question/query")

        (
            answer,
            used_vector,
            used_sql,
            citations,
            route,
            retrieval_plan,
            profile_version,
        ) = get_hybrid_answer(
            q_text,
            query.db_target,
            query.session_id,
            query.context,
            query.synthesize,
        )
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        sources = []
        if used_sql:
            sources.append("SQLite Local")
        if any("lexical" in citation.get("channels", []) for citation in citations):
            sources.append("SQLite FTS5")
        if any("dense" in citation.get("channels", []) for citation in citations):
            sources.append("FAISS + HuggingFace")
        _store_context(query.session_id, q_text, answer)
        _record_query_history(
            query_id,
            q_text,
            answer,
            query.db_target,
            route,
            latency_ms,
            citations,
            profile_version,
        )
        trace = {
            "query_id": query_id,
            "timestamp": _utc_now(),
            "question": q_text,
            "profile_version": profile_version,
            "route": route,
            "latency_ms": latency_ms,
            "stages": [
                {
                    "id": "request",
                    "label": "Request accepted",
                    "status": "complete",
                    "duration_ms": 0,
                    "detail": f"target={query.db_target}",
                },
                *retrieval_plan["stages"],
                {
                    "id": "evidence",
                    "label": "Evidence pack assembled",
                    "status": "complete",
                    "duration_ms": 0,
                    "candidates": len(citations),
                },
                {
                    "id": "synthesis",
                    "label": "Answer synthesis",
                    "status": retrieval_plan.get("synthesis_status", "complete"),
                    "duration_ms": 0,
                    "detail": (
                        None
                        if retrieval_plan.get("synthesis_status", "complete") == "complete"
                        else "local evidence mode"
                    ),
                },
            ],
            "channels": retrieval_plan["channels"],
            "settings": retrieval_plan["settings"],
            "results": citations,
        }
        save_trace(CONTROL_PLANE_DB_PATH, trace)
        confidence = round(citations[0]["score"], 3) if citations else 0
        return {
            "query_id": query_id,
            "answer": answer,
            "sources": sources,
            "citations": citations,
            "confidence_score": confidence,
            "meta": {
                "db_target": query.db_target,
                "used_vector": used_vector,
                "used_sql": used_sql,
                "model": FREE_LLM_MODEL,
                "latency_ms": latency_ms,
                "route": route,
                "rerank_topk": len(citations),
                "retrieval_profile_version": profile_version,
                "retrieval_channels": retrieval_plan["channels"],
            },
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Answer synthesis degraded to local evidence mode: %s", type(exc).__name__)
        try:
            q_text = query.question or query.query
            _ensure_control_plane()
            profile = get_active_profile(CONTROL_PLANE_DB_PATH)
            retrieval_results, retrieval_plan = _retrieve_with_profile(
                q_text,
                profile,
                include_dense=True,
            )
            citations = _citations_from_results(retrieval_results)
            latency_ms = round((time.perf_counter() - start) * 1000, 2)
            answer = (
                "Answer synthesis is temporarily unavailable. Retrieval completed "
                "in local evidence mode; inspect the ranked citations below."
            )
            _record_query_history(
                query_id,
                q_text,
                answer,
                query.db_target,
                "retrieval_only",
                latency_ms,
                citations,
                profile["version"],
            )
            trace = {
                "query_id": query_id,
                "timestamp": _utc_now(),
                "question": q_text,
                "profile_version": profile["version"],
                "route": "retrieval_only",
                "latency_ms": latency_ms,
                "stages": [
                    *retrieval_plan["stages"],
                    {
                        "id": "synthesis",
                        "label": "Answer synthesis",
                        "status": "degraded",
                        "duration_ms": 0,
                        "detail": "provider unavailable; evidence preserved",
                    },
                ],
                "channels": retrieval_plan["channels"],
                "settings": retrieval_plan["settings"],
                "results": citations,
            }
            save_trace(CONTROL_PLANE_DB_PATH, trace)
            sources = []
            if any("lexical" in item.get("channels", []) for item in citations):
                sources.append("SQLite FTS5")
            if any("dense" in item.get("channels", []) for item in citations):
                sources.append("FAISS + HuggingFace")
            return {
                "query_id": query_id,
                "answer": answer,
                "sources": sources,
                "citations": citations,
                "confidence_score": round(citations[0]["score"], 3) if citations else 0,
                "meta": {
                    "db_target": query.db_target,
                    "used_vector": any(
                        "dense" in item.get("channels", []) for item in citations
                    ),
                    "used_sql": False,
                    "model": FREE_LLM_MODEL,
                    "latency_ms": latency_ms,
                    "route": "retrieval_only",
                    "rerank_topk": len(citations),
                    "retrieval_profile_version": profile["version"],
                    "retrieval_channels": retrieval_plan["channels"],
                    "synthesis_status": "degraded",
                },
            }
        except Exception as fallback_exc:
            logger.error("RAG fallback failed: %s", fallback_exc)
            return {
                "answer": "The query could not be completed. Check service logs for the correlation ID.",
                "query_id": query_id,
                "sources": [],
                "citations": [],
                "confidence_score": 0,
                "meta": {
                    "route": "error",
                    "retrieval_profile_version": None,
                    "latency_ms": round((time.perf_counter() - start) * 1000, 2),
                },
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
    _record_ingest_event("upload", saved, rebuild, "accepted")
    return {"status": "ok", "saved": saved, "rebuild": rebuild}


@app.post("/api/v1/ingest/rebuild")
async def rebuild_index(background_tasks: BackgroundTasks):
    background_tasks.add_task(build_index, KNOWLEDGE_DIR, FAISS_INDEX_PATH)
    _record_ingest_event("rebuild", [], True, "accepted")
    return {"status": "ok", "message": "Rebuild started"}


@app.get("/api/v1/ingest/history")
async def ingestion_history():
    _seed_ingestion_history_if_missing()
    files = [
        _knowledge_file_entry(path)
        for path in sorted(KNOWLEDGE_DIR.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True)
        if path.is_file() and not path.name.startswith(".")
    ] if KNOWLEDGE_DIR.exists() else []
    return {
        "history": _read_json_list(INGEST_HISTORY_PATH),
        "files": files,
    }


@app.delete("/api/v1/ingest/files/{filename}")
async def delete_ingested_file(filename: str, background_tasks: BackgroundTasks, rebuild: bool = True):
    target = KNOWLEDGE_DIR / filename
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    target.unlink()
    if rebuild:
        background_tasks.add_task(build_index, KNOWLEDGE_DIR, FAISS_INDEX_PATH)
    _record_ingest_event("delete", [filename], rebuild, "accepted")
    return {"status": "ok", "deleted": filename, "rebuild": rebuild}


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


@app.get("/api/v1/history/queries")
async def query_history():
    return {"history": _read_json_list(QUERY_HISTORY_PATH)}


@app.get("/api/v1/evals/summary")
async def eval_summary():
    history = _read_json_list(QUERY_HISTORY_PATH)
    if not history:
        return {
            "queries": 0,
            "avg_latency_ms": 0,
            "route_breakdown": {},
            "avg_top_score": 0,
        }

    avg_latency = round(sum(item.get("latency_ms", 0) for item in history) / len(history), 2)
    scored = [item["top_score"] for item in history if item.get("top_score") is not None]
    avg_top_score = round(sum(scored) / len(scored), 3) if scored else 0
    route_breakdown: dict[str, int] = {}
    for item in history:
        route = item.get("route", "unknown")
        route_breakdown[route] = route_breakdown.get(route, 0) + 1
    return {
        "queries": len(history),
        "avg_latency_ms": avg_latency,
        "route_breakdown": route_breakdown,
        "avg_top_score": avg_top_score,
    }


def _load_golden_queries() -> list[dict[str, Any]]:
    if not GOLDEN_DATASET_PATH.exists():
        return []
    try:
        payload = json.loads(GOLDEN_DATASET_PATH.read_text(encoding="utf-8"))
        return payload if isinstance(payload, list) else payload.get("queries", [])
    except (OSError, json.JSONDecodeError):
        return []


def _replay_queries(request: ReplayRequest) -> list[dict[str, Any]]:
    selected = [
        {
            "question": item.question,
            "expected_sources": item.expected_sources,
            "origin": "request",
        }
        for item in request.queries
    ]
    if request.include_golden:
        selected.extend(
            {
                "question": item["question"],
                "expected_sources": item.get("expected_sources", []),
                "origin": "golden",
            }
            for item in _load_golden_queries()
            if item.get("question")
        )
    if request.include_history:
        selected.extend(
            {
                "question": item["question"],
                "expected_sources": [
                    source
                    for source in item.get("citation_sources", [])
                    if source
                ],
                "origin": "history",
            }
            for item in _read_json_list(QUERY_HISTORY_PATH)
            if item.get("question")
        )
    deduplicated = []
    seen = set()
    for item in selected:
        key = item["question"].strip().lower()
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(item)
    return deduplicated[: request.limit]


@app.get("/api/v1/retrieval/control-plane")
async def retrieval_control_plane():
    _ensure_control_plane()
    return control_plane_summary(CONTROL_PLANE_DB_PATH)


@app.get("/api/v1/retrieval/profiles")
async def retrieval_profiles():
    _ensure_control_plane()
    return {
        "profiles": list_profiles(CONTROL_PLANE_DB_PATH),
        "events": list_profile_events(CONTROL_PLANE_DB_PATH),
    }


@app.post("/api/v1/retrieval/profiles", status_code=201)
async def create_retrieval_profile(request: ProfileCreateRequest):
    _ensure_control_plane()
    if get_profile(CONTROL_PLANE_DB_PATH, request.version):
        raise HTTPException(status_code=409, detail="Profile version already exists")
    try:
        profile = create_profile(
            CONTROL_PLANE_DB_PATH,
            request.version,
            request.name,
            request.description,
            request.settings.model_dump(),
            request.actor,
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Profile version already exists") from exc
    return {"profile": profile}


@app.post("/api/v1/retrieval/replay")
async def replay_retrieval_policy(request: ReplayRequest):
    _ensure_control_plane()
    active = get_active_profile(CONTROL_PLANE_DB_PATH)
    current_version = request.current_profile or active["version"]
    current_profile = get_profile(CONTROL_PLANE_DB_PATH, current_version)
    candidate_profile = get_profile(CONTROL_PLANE_DB_PATH, request.candidate_profile)
    if not current_profile:
        raise HTTPException(status_code=404, detail="Current profile not found")
    if not candidate_profile:
        raise HTTPException(status_code=404, detail="Candidate profile not found")

    replay_queries = _replay_queries(request)
    if not replay_queries:
        raise HTTPException(
            status_code=400,
            detail="No replay queries available; add queries or enable the golden dataset",
        )

    items = []
    for item in replay_queries:
        question = item["question"]
        lexical_results = lexical_search(CONTROL_PLANE_DB_PATH, question, limit=12)
        dense_results = []
        dense_error = None
        if request.include_dense:
            try:
                dense_results = _dense_search(question, limit=12)
            except Exception as exc:
                dense_error = str(exc)
                logger.warning("Replay dense retrieval unavailable: %s", exc)
        channels = (lexical_results, dense_results)

        current_started = time.perf_counter()
        current_results, _ = _retrieve_with_profile(
            question,
            current_profile,
            include_dense=request.include_dense,
            prepared_channels=channels,
        )
        current_latency = round((time.perf_counter() - current_started) * 1000, 2)
        candidate_started = time.perf_counter()
        candidate_results, _ = _retrieve_with_profile(
            question,
            candidate_profile,
            include_dense=request.include_dense,
            prepared_channels=channels,
        )
        candidate_latency = round((time.perf_counter() - candidate_started) * 1000, 2)
        comparison = compare_rankings(
            question,
            item["expected_sources"],
            current_results,
            candidate_results,
            current_latency,
            candidate_latency,
        )
        comparison.update(
            {
                "origin": item["origin"],
                "channels": {
                    "lexical": len(lexical_results),
                    "dense": len(dense_results),
                },
                "dense_error": dense_error,
                "current_ranking": [
                    {
                        "source": result["source"],
                        "rank": result["rank"],
                        "score": result["score"],
                        "channels": result["channels"],
                    }
                    for result in current_results
                ],
                "candidate_ranking": [
                    {
                        "source": result["source"],
                        "rank": result["rank"],
                        "score": result["score"],
                        "channels": result["channels"],
                    }
                    for result in candidate_results
                ],
            }
        )
        items.append(comparison)

    verdict, metrics = evaluate_release_gate(items, candidate_profile["settings"])
    replay = {
        "replay_id": f"rpl_{uuid.uuid4().hex[:12]}",
        "timestamp": utc_now(),
        "current_profile": current_profile["version"],
        "candidate_profile": candidate_profile["version"],
        "verdict": verdict,
        "metrics": {
            **metrics,
            "mode": "hybrid" if request.include_dense else "lexical-only",
        },
        "items": items,
    }
    save_replay(CONTROL_PLANE_DB_PATH, replay)
    return replay


@app.get("/api/v1/retrieval/replays")
async def retrieval_replays():
    _ensure_control_plane()
    return {"replays": list_replays(CONTROL_PLANE_DB_PATH)}


@app.get("/api/v1/retrieval/replays/{replay_id}")
async def retrieval_replay_details(replay_id: str):
    _ensure_control_plane()
    replay = get_replay(CONTROL_PLANE_DB_PATH, replay_id)
    if not replay:
        raise HTTPException(status_code=404, detail="Replay not found")
    return replay


@app.get("/api/v1/retrieval/traces")
async def retrieval_traces():
    _ensure_control_plane()
    return {"traces": list_traces(CONTROL_PLANE_DB_PATH)}


@app.get("/api/v1/retrieval/traces/{query_id}")
async def retrieval_trace_details(query_id: str):
    _ensure_control_plane()
    trace = get_trace(CONTROL_PLANE_DB_PATH, query_id)
    if not trace:
        raise HTTPException(status_code=404, detail="Trace not found")
    return trace


@app.post("/api/v1/retrieval/profiles/{version}/promote")
async def promote_retrieval_profile(version: str, request: ProfileActionRequest):
    _ensure_control_plane()
    profile = get_profile(CONTROL_PLANE_DB_PATH, version)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    replay = latest_replay_for_candidate(CONTROL_PLANE_DB_PATH, version)
    if not replay or replay["verdict"] != "PASS":
        raise HTTPException(
            status_code=409,
            detail="Promotion requires a latest PASS replay for this candidate",
        )
    promoted, previous = activate_profile(
        CONTROL_PLANE_DB_PATH,
        version,
        request.actor,
        action="promoted",
    )
    return {
        "status": "promoted",
        "profile": promoted,
        "previous_profile": previous,
        "replay_id": replay["replay_id"],
    }


@app.post("/api/v1/retrieval/profiles/{version}/rollback")
async def rollback_retrieval_profile(version: str, request: ProfileActionRequest):
    _ensure_control_plane()
    profile = get_profile(CONTROL_PLANE_DB_PATH, version)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    activated, previous = activate_profile(
        CONTROL_PLANE_DB_PATH,
        version,
        request.actor,
        action="rollback",
    )
    return {
        "status": "rolled_back",
        "profile": activated,
        "previous_profile": previous,
    }


@app.post("/api/v1/retrieval/index/lexical/rebuild")
async def rebuild_retrieval_lexical_index():
    _ensure_control_plane()
    return rebuild_lexical_index(CONTROL_PLANE_DB_PATH, KNOWLEDGE_DIR)


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
