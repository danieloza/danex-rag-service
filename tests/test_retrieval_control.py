from pathlib import Path
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from main import app
from retrieval_control import reciprocal_rank_fusion


def _configure_control_plane(tmp_path, monkeypatch):
    knowledge_dir = tmp_path / "knowledge_base"
    knowledge_dir.mkdir()
    (knowledge_dir / "policy.txt").write_text(
        "Complaints must be submitted within seven calendar days. "
        "The operations team reviews a complaint within three business days.",
        encoding="utf-8",
    )
    (knowledge_dir / "vip.txt").write_text(
        "VIP customers must not wait longer than five minutes.",
        encoding="utf-8",
    )
    monkeypatch.setattr(main, "KNOWLEDGE_DIR", knowledge_dir)
    monkeypatch.setattr(
        main,
        "CONTROL_PLANE_DB_PATH",
        tmp_path / "control-plane.sqlite3",
    )
    monkeypatch.setattr(
        main,
        "QUERY_HISTORY_PATH",
        tmp_path / "query-history.json",
    )
    monkeypatch.setattr(main, "FAISS_INDEX_PATH", tmp_path / "faiss-index")
    return knowledge_dir


def test_rrf_exposes_channel_contributions():
    lexical = [
        {
            "id": "policy.txt",
            "source": "policy.txt",
            "content": "policy",
            "retrieval_score": 0.8,
        }
    ]
    dense = [
        {
            "id": "policy.txt",
            "source": "policy.txt",
            "content": "policy evidence",
            "retrieval_score": 0.9,
        },
        {
            "id": "vip.txt",
            "source": "vip.txt",
            "content": "vip evidence",
            "retrieval_score": 0.7,
        },
    ]

    results = reciprocal_rank_fusion(
        lexical,
        dense,
        {
            "rank_constant": 60,
            "top_k": 5,
            "lexical_weight": 1.0,
            "dense_weight": 1.0,
        },
    )

    assert results[0]["source"] == "policy.txt"
    assert results[0]["channels"] == ["lexical", "dense"]
    assert results[0]["contributions"]["lexical"] > 0
    assert results[0]["contributions"]["dense"] > 0


def test_replay_evaluates_candidate_and_allows_promotion(tmp_path, monkeypatch):
    _configure_control_plane(tmp_path, monkeypatch)
    client = TestClient(app)

    replay_response = client.post(
        "/api/v1/retrieval/replay",
        json={
            "include_dense": False,
            "include_golden": False,
            "include_history": False,
            "queries": [
                {
                    "question": "When must a complaint be submitted?",
                    "expected_sources": ["policy.txt"],
                },
                {
                    "question": "What is the VIP waiting time?",
                    "expected_sources": ["vip.txt"],
                },
            ],
        },
    )

    assert replay_response.status_code == 200
    replay = replay_response.json()
    assert replay["verdict"] == "PASS"
    assert replay["metrics"]["query_count"] == 2
    assert replay["items"][0]["candidate_top_source"] == "policy.txt"

    promote_response = client.post(
        "/api/v1/retrieval/profiles/rag-2026.08-candidate/promote",
        json={"actor": "test-operator"},
    )
    assert promote_response.status_code == 200
    assert promote_response.json()["profile"]["status"] == "active"
    assert promote_response.json()["replay_id"] == replay["replay_id"]


def test_query_creates_retrieval_trace_without_llm_key(tmp_path, monkeypatch):
    _configure_control_plane(tmp_path, monkeypatch)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("DANEX_ENABLE_LOCAL_EMBEDDINGS", raising=False)
    client = TestClient(app)

    query_response = client.post(
        "/api/v1/query",
        json={"question": "When must a complaint be submitted?"},
    )
    assert query_response.status_code == 200
    payload = query_response.json()
    assert payload["meta"]["route"] == "retrieval_only"
    assert payload["citations"][0]["source"] == "policy.txt"
    assert payload["meta"]["retrieval_profile_version"] == "rag-2026.07-stable"

    trace_response = client.get(
        f"/api/v1/retrieval/traces/{payload['query_id']}"
    )
    assert trace_response.status_code == 200
    trace = trace_response.json()
    assert trace["query_id"] == payload["query_id"]
    assert any(stage["id"] == "fusion" for stage in trace["stages"])


def test_query_can_explicitly_skip_llm_synthesis(tmp_path, monkeypatch):
    _configure_control_plane(tmp_path, monkeypatch)
    monkeypatch.setenv("GOOGLE_API_KEY", "configured-but-unused")

    class UnexpectedModelCall:
        def __init__(self, *args, **kwargs):
            raise AssertionError("LLM client must not be created in evidence mode")

    monkeypatch.setattr(main, "ChatGoogleGenerativeAI", UnexpectedModelCall)
    client = TestClient(app)

    response = client.post(
        "/api/v1/query",
        json={
            "question": "When must a complaint be submitted?",
            "synthesize": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["route"] == "retrieval_only"
    assert payload["citations"][0]["source"] == "policy.txt"
    assert "LLM synthesis disabled" in payload["answer"]


def test_provider_failure_degrades_without_exposing_provider_payload(tmp_path, monkeypatch):
    _configure_control_plane(tmp_path, monkeypatch)

    def failing_answer(*args, **kwargs):
        raise RuntimeError("provider-secret-payload")

    monkeypatch.setattr(main, "get_hybrid_answer", failing_answer)
    client = TestClient(app)

    response = client.post(
        "/api/v1/query",
        json={"question": "When must a complaint be submitted?"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["route"] == "retrieval_only"
    assert payload["meta"]["synthesis_status"] == "degraded"
    assert "provider-secret-payload" not in payload["answer"]
    assert payload["citations"][0]["source"] == "policy.txt"
