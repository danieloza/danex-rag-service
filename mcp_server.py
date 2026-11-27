"""Danex retrieval as an MCP server (Streamable HTTP).

The server answers from the lexical channel: SQLite FTS5 results ranked with the
active retrieval profile's RRF settings. It imports `retrieval_control` (standard
library only) and the MCP SDK, nothing from `main.py`, so it starts without
LangChain, FAISS or a model provider key. Dense retrieval and answer synthesis
stay in the HTTP API.

It is meant to run on loopback behind a gateway, which decides who may call it:

    python mcp_server.py          # http://127.0.0.1:8101/mcp
"""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from retrieval_control import (
    get_active_profile,
    get_trace as load_trace,
    initialize_control_plane,
    lexical_search,
    reciprocal_rank_fusion,
    save_trace,
    utc_now,
)

HERE = Path(__file__).resolve().parent
KNOWLEDGE_DIR = Path(os.environ.get("DANEX_KNOWLEDGE_DIR", HERE / "knowledge_base"))
DB_PATH = Path(os.environ.get("DANEX_MCP_DB", HERE / ".runtime-control-plane-mcp.sqlite3"))
MAX_QUESTION_CHARS = 500
MAX_RESULTS = 8
MAX_PASSAGE_CHARS = 800
ROUTE = "mcp_lexical"

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

server = MCPServer(
    name="danex-retrieval",
    instructions=(
        "Search the Danex salon policies and procedures. Results are ranked evidence "
        "with the source file of each passage, never a generated answer."
    ),
)

_ready_for: Path | None = None


def _ensure_ready() -> None:
    """Create the control-plane tables and the FTS5 index once per database path."""
    global _ready_for
    if _ready_for != DB_PATH:
        initialize_control_plane(DB_PATH, KNOWLEDGE_DIR)
        _ready_for = DB_PATH


def evidence_for_agent(ranked: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Shape fused results into what the calling agent receives.

    Each item in `ranked` comes from `reciprocal_rank_fusion` and carries:
    `source` (file name), `content` (the full chunk, up to ~700 characters),
    `rank`, `score` (normalised to the best result, 0-1], `rrf_score`,
    `channels`, `channel_ranks`, `channel_scores` and `contributions`.

    Whatever this returns leaves the server: through the gateway and into the
    agent's context.
    """
    # The whole chunk, not a snippet: a source-bound agent must be able to quote
    # its evidence without a second call. Chunks are ~700 characters; the cap
    # guards against an index built with larger chunks. Ranking internals
    # (RRF scores, per-channel ranks) stay in the trace, behind get_trace.
    return [
        {
            "source": item["source"],
            "rank": item["rank"],
            "score": item["score"],
            "passage": " ".join(item.get("content", "").split())[:MAX_PASSAGE_CHARS],
        }
        for item in ranked
    ]


def _trace_results(ranked: list[dict[str, Any]], evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What the agent saw, plus the ranking detail an operator needs to explain it."""
    return [
        {
            **shown,
            "rrf_score": item["rrf_score"],
            "channels": item["channels"],
            "channel_ranks": item["channel_ranks"],
            "contributions": item["contributions"],
        }
        for item, shown in zip(ranked, evidence)
    ]


@server.tool(annotations=READ_ONLY)
def search(question: str, limit: int = 5) -> dict[str, Any]:
    """Search the Danex salon policies and procedures.

    Returns up to `limit` ranked passages (at most the active profile's top_k)
    with their source files, plus a query_id for get_trace.
    """
    question = question.strip()
    if not question:
        raise ToolError("question must not be empty")
    if len(question) > MAX_QUESTION_CHARS:
        raise ToolError(f"question is longer than {MAX_QUESTION_CHARS} characters")
    limit = max(1, min(limit, MAX_RESULTS))

    _ensure_ready()
    started = time.perf_counter()
    profile = get_active_profile(DB_PATH)
    lexical = lexical_search(DB_PATH, question, limit=12)
    ranked = reciprocal_rank_fusion(lexical, [], profile["settings"])[:limit]
    latency_ms = round((time.perf_counter() - started) * 1000, 2)

    query_id = f"qry_{uuid.uuid4().hex[:12]}"
    evidence = evidence_for_agent(ranked)
    save_trace(
        DB_PATH,
        {
            "query_id": query_id,
            "timestamp": utc_now(),
            "question": question,
            "profile_version": profile["version"],
            "route": ROUTE,
            "latency_ms": latency_ms,
            "stages": [
                {"id": "lexical", "label": "FTS5 lexical retrieval", "status": "complete", "candidates": len(lexical)},
                {"id": "dense", "label": "FAISS dense retrieval", "status": "skipped", "detail": "not served over MCP"},
                {"id": "fusion", "label": "RRF fusion", "status": "complete", "candidates": len(ranked)},
            ],
            "channels": {"lexical": len(lexical), "dense": 0},
            "settings": profile["settings"],
            "results": _trace_results(ranked, evidence),
        },
    )
    return {
        "query_id": query_id,
        "profile_version": profile["version"],
        "channels": ["lexical"],
        "results": evidence,
    }


@server.tool(annotations=READ_ONLY)
def get_trace(query_id: str) -> dict[str, Any]:
    """Return the retrieval trace recorded for one search: stages, settings and results."""
    _ensure_ready()
    trace = load_trace(DB_PATH, query_id.strip())
    if trace is None:
        raise ToolError(f"no trace for query_id '{query_id}'")
    return trace


def main() -> None:
    _ensure_ready()
    server.run(
        "streamable-http",
        host=os.environ.get("DANEX_MCP_HOST", "127.0.0.1"),
        port=int(os.environ.get("DANEX_MCP_PORT", "8101")),
        stateless_http=True,
        json_response=True,
    )


if __name__ == "__main__":
    main()
