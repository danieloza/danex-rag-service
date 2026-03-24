# Architecture

## Goal

Provide a lightweight hybrid RAG service that can answer from both:

- unstructured knowledge base documents
- structured SQLite business data

The project is intentionally small, but it demonstrates the core split between semantic retrieval and deterministic SQL-backed answers.

## Request Flow

1. The API receives a question through `/api/v1/ask` or `/api/v1/query`.
2. The service loads environment configuration from the repo `.env` or shared workspace `.env.global`.
3. Semantic retrieval runs against the local FAISS index when available.
4. SQL synthesis is attempted for data-oriented questions against the selected SQLite target.
5. The service combines SQL-backed and retrieval-backed outputs into a final answer.

## Main Components

- `main.py`
  FastAPI delivery layer, hybrid answer flow, and PDF endpoints.
- `ingest.py`
  Builds the local FAISS index from text knowledge files.
- `pdf_generator.py`
  Generates downloadable PDF reports for report-style responses.
- `tests/test_health.py`
  Smoke-level health validation.
- `tests/test_api.py`
  API-level validation for request handling and PDF generation.

## Data Sources

- `knowledge_base/`
  Unstructured text loaded into FAISS.
- `salonos.db`
  Operational business data for Salonos flows.
- `danex.db`
  Additional Danex business data.

## Current Tradeoffs

- SQL generation uses model output and is intended for controlled local datasets.
- The service loads retrieval infrastructure lazily inside request handling.
- There is only smoke-level CI coverage, not full end-to-end evaluation of answer quality.

## Next Iterations

- add stricter SQL guardrails and query allowlists
- separate retrieval, SQL, and synthesis into dedicated services
- add benchmark questions and regression scoring
- add structured observability for retrieval latency and SQL execution outcomes
