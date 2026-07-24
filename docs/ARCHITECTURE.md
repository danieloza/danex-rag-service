# Architecture

## System Objective

Danex provides governed answers over:

- unstructured policy and procedure documents
- structured SQLite operational data

The system separates query-time evidence retrieval from retrieval-change governance. This makes the active ranking configuration observable and allows a candidate to be evaluated before rollout.

## Query Path

1. `/api/v1/ask` or `/api/v1/query` receives the question.
2. The active retrieval profile supplies lexical weight, dense weight, RRF constant and top-k.
3. SQLite FTS5 retrieves exact-term evidence.
4. FAISS retrieves semantic evidence using local HuggingFace embeddings.
5. Reciprocal Rank Fusion produces one ranked citation pack.
6. Operational questions can additionally route to the selected SQLite Text-to-SQL target.
7. The request either returns local evidence or performs explicit LLM synthesis.
8. Query history and the Flight Recorder persist the correlation identifier, profile version, route, stages and ranked evidence.

## Control Path

1. An operator creates an immutable candidate retrieval profile.
2. The replay endpoint loads golden, historical or supplied queries.
3. Each query receives identical lexical and dense candidate sets.
4. Active and candidate profile settings independently fuse those candidates.
5. The evaluator computes source changes, NDCG delta, citation churn, latency delta and risk.
6. The release gate returns `PASS`, `REVIEW` or `BLOCK`.
7. Promotion requires the latest replay for that candidate to be `PASS`.
8. Promotion or rollback records the actor, previous version and timestamp.

## Components

- `main.py`
  FastAPI contracts, query orchestration, model/SQL integration, replay endpoints and UI delivery.
- `retrieval_control.py`
  Profile persistence, FTS5 indexing, RRF, NDCG, release-gate evaluation, traces and replay storage.
- `ingest.py`
  Knowledge conversion, chunking, FAISS construction and lexical rebuild.
- `evals/golden_dataset.json`
  Committed query-to-source relevance judgments used by regression replay.
- `static/`
  Control Plane, Query Workspace, Knowledge Sources, Operations and guided presentation.
- `pdf_generator.py`
  Downloadable report generation.

## Persistence

The local default uses:

- `faiss_index/` for dense vectors
- `.runtime-control-plane.sqlite3` for profiles, events, lexical chunks, replay evidence and traces
- `.runtime-query-history.json` for bounded query history
- `knowledge_base/.ingest_history.json` for source-change history

The runtime files are excluded from version control. Paths can be overridden through environment variables for isolated test or demo instances.

## Security and Reliability Boundaries

- LLM synthesis is opt-in in the UI.
- Retrieval remains available when no model key is configured.
- Provider failures degrade to ranked local evidence rather than returning the provider payload.
- Candidate promotion is coupled to replay evidence.
- Query text and source excerpts are not exported to a telemetry vendor by this implementation.
- FAISS deserialization assumes the locally generated index files are trusted.
- Text-to-SQL is limited to configured local databases but still requires read-only credentials and query enforcement for production use.

## Scaling Target

A multi-replica deployment should replace the local Control Plane store with PostgreSQL, introduce migration ownership, and move vector search to an infrastructure component designed for partitioning, replication and data-residency controls. Profile activation must remain transactional so only one version is active for a tenant and region.

## Validation Layers

- pure ranking tests for RRF channel evidence
- API tests for replay, promotion and trace retrieval
- degradation tests for zero-cost evidence mode
- browser acceptance for desktop, mobile, guided presentation and console errors
- domain-owned golden queries for relevance regressions

See [RETRIEVAL_CONTROL_PLANE.md](RETRIEVAL_CONTROL_PLANE.md) for the detailed governance model.
