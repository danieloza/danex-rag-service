# Release Notes

All operator-relevant changes are recorded here. The project follows the structure of Keep a Changelog without claiming semantic-version compatibility guarantees before a tagged release.

## Unreleased

### Added

- Retrieval Control Plane with active, candidate and retired profile states.
- SQLite FTS5 lexical retrieval alongside the existing FAISS dense channel.
- Reciprocal Rank Fusion with per-channel ranks, scores and contribution evidence.
- Six-query committed golden dataset with expected source judgments.
- Counterfactual replay across golden and historical queries.
- Per-query ranking diff with NDCG delta, citation churn, classification and risk.
- Release gate covering average NDCG delta, known-answer regressions, citation churn and p95 fusion-latency delta.
- Replay-backed profile promotion, explicit rollback and operator-attributed profile events.
- Query Flight Recorder with stage durations, channel counts and ranked evidence.
- Zero-cost local evidence mode and an explicit UI opt-in for LLM synthesis.
- Guided presentation flow, responsive Control Plane UI, updated screenshots and high-resolution demo GIF.
- Configurable local paths for the Control Plane database and query history.
- MCP server (`mcp_server.py`, Streamable HTTP) with read-only `search` and `get_trace` tools over the lexical channel, for use behind an MCP gateway.

### Changed

- Query responses now include `query_id`, `retrieval_profile_version`, retrieval channel counts and RRF citation details.
- Ingestion rebuilds both dense and lexical indexes.
- RAG synthesis uses the fused citation pack as source-bound evidence.
- The FastAPI application version is now `1.0.0`.
- README and architecture documentation now describe the implemented retrieval-governance surface and deployment boundaries.

### Security and Reliability

- Model quota or provider failures degrade to local evidence mode instead of returning provider payloads to the UI.
- Candidate promotion requires the latest replay verdict to be `PASS`.
- Runtime Control Plane files, query history, browser artifacts and local environment files remain excluded from version control.
- UI controls include keyboard focus states, mobile navigation labels and reduced-motion handling.

### Validation

- Backend suite expanded from six to nine tests during implementation.
- Browser acceptance performed at 1440 px desktop and 375 px mobile widths.
- Hybrid replay verified against the committed golden set with two improved top-source rankings, `NDCG Δ +0.123`, and zero known-answer regressions in the captured local run.
- Query evidence mode, guided demo, Flight Recorder and browser console checked through real UI interactions.

### Known Boundaries

- SQLite and local FAISS remain single-node defaults.
- The portfolio build does not integrate corporate IAM; profile actors must be derived from verified identity claims before company deployment.
- The committed golden set is a reference dataset and does not replace domain-owner relevance judgments.
- Text-to-SQL requires additional database permissions and query guardrails for production use.
