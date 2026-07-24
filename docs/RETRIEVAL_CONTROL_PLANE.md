# Retrieval Control Plane

## Purpose

The Retrieval Control Plane separates two responsibilities:

- serving the active retrieval configuration at query time
- evaluating candidate configuration changes before promotion

This prevents retrieval weights, top-k values, fusion settings or index changes from being treated as unreviewed application configuration. Each query is correlated with the profile that produced its citations.

## Retrieval Plan

### Lexical channel

SQLite FTS5 indexes text and Markdown knowledge chunks. It is optimized for exact policy terms, identifiers, product names and phrases whose wording matters.

### Dense channel

FAISS searches locally generated `all-MiniLM-L6-v2` embeddings. It covers semantic similarity when the user and source use different wording.

### Fusion

Reciprocal Rank Fusion combines the two ranked result sets:

```text
contribution(channel, document) =
    channel_weight / (rank_constant + channel_rank)
```

Raw FTS5 and vector-distance values are retained for inspection but are not added directly. The response exposes:

- final fused rank
- normalized fused score
- participating channels
- rank within each channel
- per-channel RRF contribution

## Retrieval Profiles

A profile contains:

```json
{
  "version": "rag-2026.08-candidate",
  "settings": {
    "lexical_weight": 1.2,
    "dense_weight": 1.0,
    "rank_constant": 30,
    "top_k": 5,
    "min_ndcg_delta": -0.02,
    "max_citation_churn": 0.55,
    "max_p95_latency_delta_ms": 250
  }
}
```

Profile versions are immutable after creation. The local store maintains one active version and zero or more candidate or retired versions.

## Counterfactual Replay

Replay uses the same query against the active and candidate profiles. Both profiles receive the same lexical and dense candidate sets, isolating the effect of fusion configuration.

The replay dataset can contain:

- committed golden queries with source relevance judgments
- recent query history with the previously selected citation set as a reference
- request-supplied evaluation cases

Each comparison records:

- current and candidate rankings
- current and candidate top source
- NDCG for judged queries
- NDCG delta
- citation-set churn
- fusion latency delta
- classification: `unchanged`, `reordered`, `improved`, or `regressed`
- risk: `safe`, `review`, or `block`

Historical citations are useful regression indicators but are not a substitute for human-owned ground truth.

## Release Gate

The candidate receives one of three verdicts:

- `PASS` — all thresholds pass and no known-answer regression is present
- `REVIEW` — thresholds pass but a ranking change needs operator review
- `BLOCK` — at least one release threshold fails

Promotion requires the latest replay for the selected candidate to return `PASS`. The promotion record includes:

- actor
- promoted profile
- previous active profile
- timestamp
- supporting replay identifier

Rollback is explicit and creates a separate event.

## Query Flight Recorder

Every successful query stores a bounded trace:

```text
request
  ├─ FTS5 lexical retrieval
  ├─ FAISS dense retrieval
  ├─ RRF fusion
  ├─ evidence pack assembly
  └─ answer synthesis or local evidence fallback
```

The trace includes stage status, duration, candidate count, active profile version and ranked citation details. Query text and source snippets may contain sensitive data; a company deployment must apply retention, redaction and role-based access policies.

## Failure Behavior

Retrieval does not depend on a paid LLM call. If synthesis is disabled, no model request is made. If a configured model fails or its quota is exhausted:

1. the provider error is logged by type rather than returned verbatim
2. lexical and dense retrieval are preserved
3. the API returns a source-ranked local evidence response
4. the trace marks synthesis as degraded

## Persistence

The default store is `.runtime-control-plane.sqlite3`. It contains:

- retrieval profiles
- profile events
- lexical knowledge chunks and the FTS5 index
- replay results
- query traces

This is appropriate for local execution and portfolio validation. Multi-replica operation requires a shared transactional store, migration management, backup policy and concurrency tests.

## Promotion Sequence

```text
create candidate
      │
      ▼
replay golden + history
      │
      ├── BLOCK ──► revise profile
      │
      ├── REVIEW ─► operator analysis
      │
      └── PASS
            │
            ▼
     promote candidate
            │
            ▼
   record actor + replay
            │
            ▼
     monitor new traces
            │
            └── explicit rollback if required
```

## Deployment Extensions

Before organizational use:

- derive `actor` from IAM claims rather than a request body
- add tenant, region, data-residency and source-authorization filters before retrieval
- move profile and replay persistence to PostgreSQL
- use a managed or partitioned vector index for horizontal scaling
- export spans and metrics to an approved telemetry backend
- prevent raw query and document text from leaving defined security boundaries
- establish domain-owned qrels, minimum coverage and release sign-off
