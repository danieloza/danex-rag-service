from pathlib import Path
import sys

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
