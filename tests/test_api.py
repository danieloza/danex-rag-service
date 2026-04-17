from pathlib import Path
import sys
import json

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import app


def test_query_endpoint_rejects_empty_question():
    client = TestClient(app)

    response = client.post("/api/v1/query", json={"question": "", "query": ""})

    assert response.status_code == 400
    assert response.json()["detail"] == "Empty question/query"


def test_query_endpoint_returns_informative_message_without_api_key(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    client = TestClient(app)

    response = client.post(
        "/api/v1/query",
        json={"question": "Ile rezerwacji bylo wczoraj?", "db_target": "salonos"},
    )

    assert response.status_code == 200
    assert "Missing GOOGLE_API_KEY" in response.json()["answer"]


def test_pdf_endpoint_creates_report_and_download_url(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/api/v1/report/pdf",
        json={"title": "Weekly Summary", "content": "Line 1\nLine 2"},
    )

    body = response.json()

    assert response.status_code == 200
    assert body["status"] == "success"
    generated_name = body["download_url"].rsplit("/", 1)[-1]
    assert (tmp_path / "reports" / generated_name).exists()


def test_query_history_and_eval_summary(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    history_path = tmp_path / ".runtime-query-history.json"
    history_path.write_text(
        json.dumps(
            [
                {
                    "timestamp": "2026-04-18T10:00:00+00:00",
                    "question": "Jak wyglada procedura reklamacji?",
                    "answer_preview": "Preview",
                    "db_target": "salonos",
                    "route": "vector",
                    "latency_ms": 123.0,
                    "citations_count": 2,
                    "top_score": 0.88,
                }
            ]
        ),
        encoding="utf-8",
    )
    client = TestClient(app)

    history_response = client.get("/api/v1/history/queries")
    eval_response = client.get("/api/v1/evals/summary")

    assert history_response.status_code == 200
    assert len(history_response.json()["history"]) == 1
    assert eval_response.status_code == 200
    assert eval_response.json()["queries"] == 1
    assert eval_response.json()["avg_top_score"] == 0.88


def test_ingestion_history_and_delete_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    knowledge_dir = tmp_path / "knowledge_base"
    knowledge_dir.mkdir()
    sample = knowledge_dir / "sample.txt"
    sample.write_text("hello", encoding="utf-8")
    (knowledge_dir / ".ingest_history.json").write_text(
        json.dumps(
            [
                {
                    "timestamp": "2026-04-18T10:00:00+00:00",
                    "action": "upload",
                    "files": ["sample.txt"],
                    "rebuild": True,
                    "status": "accepted",
                }
            ]
        ),
        encoding="utf-8",
    )
    client = TestClient(app)

    history_response = client.get("/api/v1/ingest/history")
    assert history_response.status_code == 200
    assert history_response.json()["files"][0]["name"] == "sample.txt"

    delete_response = client.delete("/api/v1/ingest/files/sample.txt?rebuild=false")
    assert delete_response.status_code == 200
    assert delete_response.json()["deleted"] == "sample.txt"
    assert not sample.exists()
