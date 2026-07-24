# Case Study

## Problem

Operational teams often need one answer assembled from two source classes:

- policy and procedure documents
- current business records

Document-only RAG cannot answer operational totals reliably. Text-to-SQL alone cannot explain policy. Combining both creates a second problem: retrieval behavior changes whenever the corpus, embeddings, ranking weights or top-k settings change.

Without controlled replay, a team cannot show whether a candidate configuration:

- preserves previously correct sources
- improves known weak queries
- creates a relevance regression
- changes citations beyond an accepted threshold
- stays within the latency budget

## Implemented Approach

Danex combines:

- SQLite FTS5 lexical search
- FAISS semantic search with local embeddings
- Reciprocal Rank Fusion
- optional Gemini answer synthesis
- controlled SQLite Text-to-SQL
- versioned retrieval profiles
- golden and historical replay
- release-gate evaluation
- query-level retrieval traces

The captured candidate replay corrected two top-source rankings across the six committed golden cases, raised average NDCG by `0.123`, and produced no known-answer regressions.

## Operational Outcome

The platform can now answer:

- which profile served a historical query
- why a document ranked first
- which retrieval channel contributed to that rank
- whether a candidate changes the top source
- whether a regression gate allows promotion
- which replay supported a configuration change
- whether the response used paid synthesis or local evidence mode

## Portfolio Signal

The implementation demonstrates work across:

- retrieval engineering
- API and persistence design
- evaluation methodology
- controlled-change workflows
- failure degradation
- operator-facing product design
- evidence-based release communication

## Remaining Production Work

- company IAM and role mapping
- shared transactional persistence
- tenant and region boundaries
- managed vector infrastructure
- larger domain-owned relevance datasets
- trace retention and redaction policy
- hardened read-only Text-to-SQL execution
- production SLOs and telemetry export
