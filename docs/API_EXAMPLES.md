# API Examples

The examples assume the service is running at `http://127.0.0.1:8002`.

## Health

```bash
curl http://127.0.0.1:8002/health
```

```json
{
  "status": "ok",
  "free_mode": true,
  "local_embeddings": true
}
```

## Query in local evidence mode

```bash
curl -X POST http://127.0.0.1:8002/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Ile godzin przed wizytą można ją anulować bez opłaty?",
    "db_target": "salonos",
    "session_id": "demo-session",
    "synthesize": false
  }'
```

Representative response:

```json
{
  "query_id": "qry_3c22e93c335a",
  "answer": "LLM synthesis disabled. Retrieval completed in local evidence mode; inspect the ranked citations below or configure the key for answer synthesis.",
  "sources": [
    "SQLite FTS5",
    "FAISS + HuggingFace"
  ],
  "citations": [
    {
      "source": "regulamin_salonu_2026.txt",
      "score": 1.0,
      "rank": 1,
      "channels": [
        "lexical",
        "dense"
      ],
      "channel_ranks": {
        "lexical": 1,
        "dense": 1
      },
      "contributions": {
        "lexical": 0.016393,
        "dense": 0.017213
      }
    }
  ],
  "meta": {
    "route": "retrieval_only",
    "retrieval_profile_version": "rag-2026.07-stable",
    "retrieval_channels": {
      "lexical": 2,
      "dense": 11
    }
  }
}
```

## Control Plane summary

```bash
curl http://127.0.0.1:8002/api/v1/retrieval/control-plane
```

The response includes active and candidate profiles, latest replay, recent traces, profile events and indexed lexical chunk count.

## Create a candidate profile

```bash
curl -X POST http://127.0.0.1:8002/api/v1/retrieval/profiles \
  -H "Content-Type: application/json" \
  -d '{
    "version": "rag-2026.09-candidate",
    "name": "September precision candidate",
    "description": "Candidate profile for controlled replay.",
    "actor": "retrieval-platform-owner",
    "settings": {
      "lexical_weight": 1.25,
      "dense_weight": 1.0,
      "rank_constant": 30,
      "top_k": 5,
      "min_ndcg_delta": -0.02,
      "max_citation_churn": 0.45,
      "max_p95_latency_delta_ms": 200
    }
  }'
```

## Replay a candidate

```bash
curl -X POST http://127.0.0.1:8002/api/v1/retrieval/replay \
  -H "Content-Type: application/json" \
  -d '{
    "candidate_profile": "rag-2026.08-candidate",
    "include_golden": true,
    "include_history": true,
    "include_dense": true,
    "limit": 20
  }'
```

Representative summary:

```json
{
  "replay_id": "rpl_86d2ef48606d",
  "current_profile": "rag-2026.07-stable",
  "candidate_profile": "rag-2026.08-candidate",
  "verdict": "PASS",
  "metrics": {
    "query_count": 6,
    "avg_ndcg_delta": 0.123,
    "avg_citation_churn": 0.0,
    "regressions": 0,
    "mode": "hybrid"
  }
}
```

## Read a replay

```bash
curl http://127.0.0.1:8002/api/v1/retrieval/replays/rpl_86d2ef48606d
```

## Promote a passing candidate

```bash
curl -X POST http://127.0.0.1:8002/api/v1/retrieval/profiles/rag-2026.08-candidate/promote \
  -H "Content-Type: application/json" \
  -d '{"actor": "retrieval-platform-owner"}'
```

A candidate without a latest `PASS` replay receives `409 Conflict`.

## Roll back

```bash
curl -X POST http://127.0.0.1:8002/api/v1/retrieval/profiles/rag-2026.07-stable/rollback \
  -H "Content-Type: application/json" \
  -d '{"actor": "incident-commander"}'
```

## Read a query trace

```bash
curl http://127.0.0.1:8002/api/v1/retrieval/traces/qry_3c22e93c335a
```

## Rebuild the lexical index

```bash
curl -X POST http://127.0.0.1:8002/api/v1/retrieval/index/lexical/rebuild
```

The standard ingestion endpoints rebuild both the lexical and dense indexes.
