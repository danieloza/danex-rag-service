from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_PROFILES = [
    {
        "version": "rag-2026.07-stable",
        "name": "Stable production baseline",
        "status": "active",
        "description": "Dense-biased baseline retained for controlled comparison.",
        "settings": {
            "lexical_weight": 1.0,
            "dense_weight": 1.05,
            "rank_constant": 60,
            "top_k": 5,
            "min_ndcg_delta": -0.02,
            "max_citation_churn": 0.55,
            "max_p95_latency_delta_ms": 250,
        },
    },
    {
        "version": "rag-2026.08-candidate",
        "name": "Precision candidate",
        "status": "candidate",
        "description": "Lexical-aware candidate intended to improve exact policy retrieval.",
        "settings": {
            "lexical_weight": 1.2,
            "dense_weight": 1.0,
            "rank_constant": 30,
            "top_k": 5,
            "min_ndcg_delta": -0.02,
            "max_citation_churn": 0.55,
            "max_p95_latency_delta_ms": 250,
        },
    },
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def initialize_control_plane(db_path: Path, knowledge_dir: Path) -> None:
    with _connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS retrieval_profiles (
                version TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                status TEXT NOT NULL,
                description TEXT NOT NULL,
                settings_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                promoted_at TEXT
            );

            CREATE TABLE IF NOT EXISTS profile_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                action TEXT NOT NULL,
                profile_version TEXT NOT NULL,
                previous_version TEXT,
                actor TEXT NOT NULL,
                details_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS retrieval_traces (
                query_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                question TEXT NOT NULL,
                profile_version TEXT NOT NULL,
                route TEXT NOT NULL,
                latency_ms REAL NOT NULL,
                trace_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS retrieval_replays (
                replay_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                current_profile TEXT NOT NULL,
                candidate_profile TEXT NOT NULL,
                verdict TEXT NOT NULL,
                metrics_json TEXT NOT NULL,
                items_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS knowledge_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                content_hash TEXT NOT NULL UNIQUE
            );
            """
        )
        try:
            connection.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts
                USING fts5(
                    source UNINDEXED,
                    chunk_index UNINDEXED,
                    content,
                    tokenize='unicode61 remove_diacritics 2'
                )
                """
            )
        except sqlite3.OperationalError:
            # Some minimal SQLite builds omit FTS5. Manual lexical scoring remains available.
            pass

        existing = connection.execute(
            "SELECT COUNT(*) AS count FROM retrieval_profiles"
        ).fetchone()["count"]
        if not existing:
            for profile in DEFAULT_PROFILES:
                connection.execute(
                    """
                    INSERT INTO retrieval_profiles (
                        version, name, status, description, settings_json, created_at, promoted_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        profile["version"],
                        profile["name"],
                        profile["status"],
                        profile["description"],
                        json.dumps(profile["settings"]),
                        utc_now(),
                        utc_now() if profile["status"] == "active" else None,
                    ),
                )
            connection.execute(
                """
                INSERT INTO profile_events (
                    timestamp, action, profile_version, previous_version, actor, details_json
                ) VALUES (?, 'bootstrap', ?, NULL, 'system', ?)
                """,
                (
                    utc_now(),
                    DEFAULT_PROFILES[0]["version"],
                    json.dumps({"reason": "Initial controlled retrieval baseline"}),
                ),
            )

        chunk_count = connection.execute(
            "SELECT COUNT(*) AS count FROM knowledge_chunks"
        ).fetchone()["count"]
    if chunk_count == 0 and knowledge_dir.exists():
        rebuild_lexical_index(db_path, knowledge_dir)


def _row_to_profile(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "version": row["version"],
        "name": row["name"],
        "status": row["status"],
        "description": row["description"],
        "settings": json.loads(row["settings_json"]),
        "created_at": row["created_at"],
        "promoted_at": row["promoted_at"],
    }


def list_profiles(db_path: Path) -> list[dict[str, Any]]:
    with _connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT * FROM retrieval_profiles
            ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'candidate' THEN 1 ELSE 2 END,
                     created_at DESC
            """
        ).fetchall()
    return [_row_to_profile(row) for row in rows]


def get_profile(db_path: Path, version: str) -> dict[str, Any] | None:
    with _connect(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM retrieval_profiles WHERE version = ?",
            (version,),
        ).fetchone()
    return _row_to_profile(row) if row else None


def get_active_profile(db_path: Path) -> dict[str, Any]:
    with _connect(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM retrieval_profiles WHERE status = 'active' LIMIT 1"
        ).fetchone()
    if not row:
        raise RuntimeError("No active retrieval profile")
    return _row_to_profile(row)


def create_profile(
    db_path: Path,
    version: str,
    name: str,
    description: str,
    settings: dict[str, Any],
    actor: str,
) -> dict[str, Any]:
    now = utc_now()
    with _connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO retrieval_profiles (
                version, name, status, description, settings_json, created_at, promoted_at
            ) VALUES (?, ?, 'candidate', ?, ?, ?, NULL)
            """,
            (version, name, description, json.dumps(settings), now),
        )
        connection.execute(
            """
            INSERT INTO profile_events (
                timestamp, action, profile_version, previous_version, actor, details_json
            ) VALUES (?, 'created', ?, NULL, ?, ?)
            """,
            (now, version, actor, json.dumps({"settings": settings})),
        )
    profile = get_profile(db_path, version)
    if not profile:
        raise RuntimeError("Profile creation did not persist")
    return profile


def list_profile_events(db_path: Path, limit: int = 20) -> list[dict[str, Any]]:
    with _connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT * FROM profile_events
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "timestamp": row["timestamp"],
            "action": row["action"],
            "profile_version": row["profile_version"],
            "previous_version": row["previous_version"],
            "actor": row["actor"],
            "details": json.loads(row["details_json"]),
        }
        for row in rows
    ]


def activate_profile(
    db_path: Path,
    version: str,
    actor: str,
    action: str = "promoted",
) -> tuple[dict[str, Any], str | None]:
    now = utc_now()
    with _connect(db_path) as connection:
        target = connection.execute(
            "SELECT * FROM retrieval_profiles WHERE version = ?",
            (version,),
        ).fetchone()
        if not target:
            raise KeyError(version)
        active = connection.execute(
            "SELECT version FROM retrieval_profiles WHERE status = 'active' LIMIT 1"
        ).fetchone()
        previous = active["version"] if active else None
        if previous == version:
            return _row_to_profile(target), previous
        if previous:
            connection.execute(
                "UPDATE retrieval_profiles SET status = 'retired' WHERE version = ?",
                (previous,),
            )
        connection.execute(
            """
            UPDATE retrieval_profiles
            SET status = 'active', promoted_at = ?
            WHERE version = ?
            """,
            (now, version),
        )
        connection.execute(
            """
            INSERT INTO profile_events (
                timestamp, action, profile_version, previous_version, actor, details_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                now,
                action,
                version,
                previous,
                actor,
                json.dumps({"controlled_change": True}),
            ),
        )
    profile = get_profile(db_path, version)
    if not profile:
        raise RuntimeError("Profile activation did not persist")
    return profile, previous


def _iter_knowledge_files(knowledge_dir: Path) -> Iterable[Path]:
    for path in sorted(knowledge_dir.rglob("*")):
        if path.is_file() and not path.name.startswith(".") and path.suffix.lower() in {".txt", ".md"}:
            yield path


def _chunk_text(text: str, chunk_size: int = 700, overlap: int = 90) -> list[str]:
    cleaned = text.replace("\r\n", "\n").strip()
    if not cleaned:
        return []
    chunks: list[str] = []
    cursor = 0
    while cursor < len(cleaned):
        end = min(cursor + chunk_size, len(cleaned))
        if end < len(cleaned):
            split_at = cleaned.rfind("\n", cursor + chunk_size // 2, end)
            if split_at > cursor:
                end = split_at
        chunk = cleaned[cursor:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(cleaned):
            break
        cursor = max(end - overlap, cursor + 1)
    return chunks


def rebuild_lexical_index(db_path: Path, knowledge_dir: Path) -> dict[str, Any]:
    files = 0
    chunks: list[tuple[str, int, str, str]] = []
    for path in _iter_knowledge_files(knowledge_dir):
        files += 1
        text = path.read_text(encoding="utf-8", errors="ignore")
        source = path.name
        for index, content in enumerate(_chunk_text(text)):
            content_hash = hashlib.sha256(
                f"{source}:{index}:{content}".encode("utf-8")
            ).hexdigest()
            chunks.append((source, index, content, content_hash))

    with _connect(db_path) as connection:
        connection.execute("DELETE FROM knowledge_chunks")
        try:
            connection.execute("DELETE FROM knowledge_fts")
            fts_available = True
        except sqlite3.OperationalError:
            fts_available = False
        for source, chunk_index, content, content_hash in chunks:
            connection.execute(
                """
                INSERT INTO knowledge_chunks (source, chunk_index, content, content_hash)
                VALUES (?, ?, ?, ?)
                """,
                (source, chunk_index, content, content_hash),
            )
            if fts_available:
                connection.execute(
                    """
                    INSERT INTO knowledge_fts (source, chunk_index, content)
                    VALUES (?, ?, ?)
                    """,
                    (source, chunk_index, content),
                )
    return {
        "files": files,
        "chunks": len(chunks),
        "fts5": fts_available,
        "indexed_at": utc_now(),
    }


def _query_tokens(question: str) -> list[str]:
    stop_words = {
        "about",
        "after",
        "before",
        "czy",
        "dla",
        "how",
        "jak",
        "jest",
        "kiedy",
        "ktore",
        "oraz",
        "the",
        "this",
        "what",
        "with",
        "which",
    }
    tokens = re.findall(r"[^\W_]{2,}", question.lower(), flags=re.UNICODE)
    return list(dict.fromkeys(token for token in tokens if token not in stop_words))


def _result_id(source: str) -> str:
    return Path(source).name.lower()


def lexical_search(
    db_path: Path,
    question: str,
    limit: int = 12,
) -> list[dict[str, Any]]:
    tokens = _query_tokens(question)
    if not tokens:
        return []
    match_query = " OR ".join(f'"{token.replace(chr(34), "")}"' for token in tokens[:12])
    with _connect(db_path) as connection:
        try:
            rows = connection.execute(
                """
                SELECT source, chunk_index, content, bm25(knowledge_fts) AS lexical_raw
                FROM knowledge_fts
                WHERE knowledge_fts MATCH ?
                ORDER BY lexical_raw
                LIMIT ?
                """,
                (match_query, limit),
            ).fetchall()
            results = [
                {
                    "id": _result_id(row["source"]),
                    "source": row["source"],
                    "content": row["content"],
                    "retrieval_score": round(1 / (1 + abs(row["lexical_raw"])), 6),
                }
                for row in rows
            ]
        except sqlite3.OperationalError:
            rows = connection.execute(
                "SELECT source, chunk_index, content FROM knowledge_chunks"
            ).fetchall()
            scored = []
            for row in rows:
                content_lower = row["content"].lower()
                score = sum(content_lower.count(token) for token in tokens)
                if score:
                    scored.append((score, row))
            scored.sort(key=lambda item: item[0], reverse=True)
            results = [
                {
                    "id": _result_id(row["source"]),
                    "source": row["source"],
                    "content": row["content"],
                    "retrieval_score": round(score / max(len(tokens), 1), 6),
                }
                for score, row in scored[:limit]
            ]
    return _deduplicate_results(results)


def _deduplicate_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduplicated = []
    for result in results:
        result_id = result.get("id") or _result_id(result.get("source", "unknown"))
        if result_id in seen:
            continue
        seen.add(result_id)
        deduplicated.append({**result, "id": result_id})
    return deduplicated


def reciprocal_rank_fusion(
    lexical_results: list[dict[str, Any]],
    dense_results: list[dict[str, Any]],
    settings: dict[str, Any],
) -> list[dict[str, Any]]:
    rank_constant = max(int(settings.get("rank_constant", 60)), 1)
    channel_weights = {
        "lexical": float(settings.get("lexical_weight", 1.0)),
        "dense": float(settings.get("dense_weight", 1.0)),
    }
    fused: dict[str, dict[str, Any]] = {}
    for channel, results in (
        ("lexical", _deduplicate_results(lexical_results)),
        ("dense", _deduplicate_results(dense_results)),
    ):
        for rank, result in enumerate(results, start=1):
            result_id = result["id"]
            entry = fused.setdefault(
                result_id,
                {
                    "id": result_id,
                    "source": Path(result.get("source", "unknown")).name,
                    "content": result.get("content", ""),
                    "rrf_score": 0.0,
                    "channels": [],
                    "channel_ranks": {},
                    "channel_scores": {},
                    "contributions": {},
                },
            )
            contribution = channel_weights[channel] / (rank_constant + rank)
            entry["rrf_score"] += contribution
            entry["channels"].append(channel)
            entry["channel_ranks"][channel] = rank
            entry["channel_scores"][channel] = result.get("retrieval_score")
            entry["contributions"][channel] = round(contribution, 6)
            if len(result.get("content", "")) > len(entry.get("content", "")):
                entry["content"] = result["content"]

    ranked = sorted(
        fused.values(),
        key=lambda item: (-item["rrf_score"], item["source"]),
    )
    top_k = max(int(settings.get("top_k", 5)), 1)
    ranked = ranked[:top_k]
    max_score = ranked[0]["rrf_score"] if ranked else 1
    for rank, item in enumerate(ranked, start=1):
        item["rank"] = rank
        item["score"] = round(item["rrf_score"] / max_score, 4)
        item["rrf_score"] = round(item["rrf_score"], 6)
    return ranked


def ndcg_at_k(results: list[dict[str, Any]], expected_sources: list[str], k: int) -> float | None:
    if not expected_sources:
        return None
    expected = {Path(source).name.lower() for source in expected_sources}
    relevances = [
        1 if Path(result.get("source", "")).name.lower() in expected else 0
        for result in results[:k]
    ]
    dcg = sum(rel / math.log2(index + 2) for index, rel in enumerate(relevances))
    ideal = [1] * min(len(expected), k)
    ideal.extend([0] * max(k - len(ideal), 0))
    idcg = sum(rel / math.log2(index + 2) for index, rel in enumerate(ideal[:k]))
    return round(dcg / idcg, 4) if idcg else 0.0


def compare_rankings(
    question: str,
    expected_sources: list[str],
    current_results: list[dict[str, Any]],
    candidate_results: list[dict[str, Any]],
    current_latency_ms: float,
    candidate_latency_ms: float,
) -> dict[str, Any]:
    current_sources = [item["source"] for item in current_results]
    candidate_sources = [item["source"] for item in candidate_results]
    current_set = set(current_sources)
    candidate_set = set(candidate_sources)
    union = current_set | candidate_set
    churn = 1 - (len(current_set & candidate_set) / len(union)) if union else 0
    current_ndcg = ndcg_at_k(current_results, expected_sources, len(current_results) or 1)
    candidate_ndcg = ndcg_at_k(candidate_results, expected_sources, len(candidate_results) or 1)
    ndcg_delta = (
        round(candidate_ndcg - current_ndcg, 4)
        if current_ndcg is not None and candidate_ndcg is not None
        else None
    )
    top_changed = (current_sources[:1] or [None])[0] != (candidate_sources[:1] or [None])[0]
    if ndcg_delta is not None and ndcg_delta < 0:
        classification = "regressed"
        risk = "block"
    elif ndcg_delta is not None and ndcg_delta > 0:
        classification = "improved"
        risk = "safe"
    elif top_changed or churn > 0:
        classification = "reordered"
        risk = "review"
    else:
        classification = "unchanged"
        risk = "safe"
    return {
        "question": question,
        "expected_sources": expected_sources,
        "current_sources": current_sources,
        "candidate_sources": candidate_sources,
        "current_top_source": current_sources[0] if current_sources else None,
        "candidate_top_source": candidate_sources[0] if candidate_sources else None,
        "current_ndcg": current_ndcg,
        "candidate_ndcg": candidate_ndcg,
        "ndcg_delta": ndcg_delta,
        "citation_churn": round(churn, 4),
        "latency_delta_ms": round(candidate_latency_ms - current_latency_ms, 2),
        "classification": classification,
        "risk": risk,
    }


def evaluate_release_gate(
    items: list[dict[str, Any]],
    candidate_settings: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    ndcg_deltas = [item["ndcg_delta"] for item in items if item["ndcg_delta"] is not None]
    avg_ndcg_delta = round(sum(ndcg_deltas) / len(ndcg_deltas), 4) if ndcg_deltas else 0
    avg_churn = round(
        sum(item["citation_churn"] for item in items) / len(items),
        4,
    ) if items else 0
    latency_deltas = sorted(item["latency_delta_ms"] for item in items)
    p95_index = max(math.ceil(len(latency_deltas) * 0.95) - 1, 0)
    p95_latency_delta = latency_deltas[p95_index] if latency_deltas else 0
    regressions = sum(item["classification"] == "regressed" for item in items)
    reviews = sum(item["risk"] == "review" for item in items)

    checks = [
        {
            "id": "quality",
            "label": "Average NDCG delta",
            "actual": avg_ndcg_delta,
            "threshold": candidate_settings.get("min_ndcg_delta", -0.02),
            "passed": avg_ndcg_delta >= candidate_settings.get("min_ndcg_delta", -0.02),
        },
        {
            "id": "regressions",
            "label": "Known-answer regressions",
            "actual": regressions,
            "threshold": 0,
            "passed": regressions == 0,
        },
        {
            "id": "citation_churn",
            "label": "Average citation churn",
            "actual": avg_churn,
            "threshold": candidate_settings.get("max_citation_churn", 0.55),
            "passed": avg_churn <= candidate_settings.get("max_citation_churn", 0.55),
        },
        {
            "id": "latency",
            "label": "P95 latency delta (ms)",
            "actual": p95_latency_delta,
            "threshold": candidate_settings.get("max_p95_latency_delta_ms", 250),
            "passed": p95_latency_delta
            <= candidate_settings.get("max_p95_latency_delta_ms", 250),
        },
    ]
    if any(not check["passed"] for check in checks):
        verdict = "BLOCK"
    elif reviews:
        verdict = "REVIEW"
    else:
        verdict = "PASS"
    return verdict, {
        "query_count": len(items),
        "avg_ndcg_delta": avg_ndcg_delta,
        "avg_citation_churn": avg_churn,
        "p95_latency_delta_ms": round(p95_latency_delta, 2),
        "regressions": regressions,
        "reviews": reviews,
        "checks": checks,
    }


def save_trace(db_path: Path, trace: dict[str, Any]) -> None:
    with _connect(db_path) as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO retrieval_traces (
                query_id, timestamp, question, profile_version, route, latency_ms, trace_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trace["query_id"],
                trace["timestamp"],
                trace["question"],
                trace["profile_version"],
                trace["route"],
                trace["latency_ms"],
                json.dumps(trace),
            ),
        )


def list_traces(db_path: Path, limit: int = 20) -> list[dict[str, Any]]:
    with _connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT trace_json FROM retrieval_traces
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [json.loads(row["trace_json"]) for row in rows]


def get_trace(db_path: Path, query_id: str) -> dict[str, Any] | None:
    with _connect(db_path) as connection:
        row = connection.execute(
            "SELECT trace_json FROM retrieval_traces WHERE query_id = ?",
            (query_id,),
        ).fetchone()
    return json.loads(row["trace_json"]) if row else None


def save_replay(db_path: Path, replay: dict[str, Any]) -> None:
    with _connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO retrieval_replays (
                replay_id, timestamp, current_profile, candidate_profile,
                verdict, metrics_json, items_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                replay["replay_id"],
                replay["timestamp"],
                replay["current_profile"],
                replay["candidate_profile"],
                replay["verdict"],
                json.dumps(replay["metrics"]),
                json.dumps(replay["items"]),
            ),
        )


def _row_to_replay(row: sqlite3.Row, include_items: bool = True) -> dict[str, Any]:
    replay = {
        "replay_id": row["replay_id"],
        "timestamp": row["timestamp"],
        "current_profile": row["current_profile"],
        "candidate_profile": row["candidate_profile"],
        "verdict": row["verdict"],
        "metrics": json.loads(row["metrics_json"]),
    }
    if include_items:
        replay["items"] = json.loads(row["items_json"])
    return replay


def list_replays(db_path: Path, limit: int = 10) -> list[dict[str, Any]]:
    with _connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT * FROM retrieval_replays
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_row_to_replay(row) for row in rows]


def get_replay(db_path: Path, replay_id: str) -> dict[str, Any] | None:
    with _connect(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM retrieval_replays WHERE replay_id = ?",
            (replay_id,),
        ).fetchone()
    return _row_to_replay(row) if row else None


def latest_replay_for_candidate(
    db_path: Path,
    candidate_profile: str,
) -> dict[str, Any] | None:
    with _connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT * FROM retrieval_replays
            WHERE candidate_profile = ?
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (candidate_profile,),
        ).fetchone()
    return _row_to_replay(row) if row else None


def control_plane_summary(db_path: Path) -> dict[str, Any]:
    profiles = list_profiles(db_path)
    active = next((profile for profile in profiles if profile["status"] == "active"), None)
    candidate = next((profile for profile in profiles if profile["status"] == "candidate"), None)
    replays = list_replays(db_path, limit=5)
    traces = list_traces(db_path, limit=8)
    latest = replays[0] if replays else None
    with _connect(db_path) as connection:
        chunks = connection.execute(
            "SELECT COUNT(*) AS count FROM knowledge_chunks"
        ).fetchone()["count"]
    return {
        "active_profile": active,
        "candidate_profile": candidate,
        "latest_replay": latest,
        "replays": replays,
        "traces": traces,
        "profile_events": list_profile_events(db_path),
        "indexed_chunks": chunks,
    }
