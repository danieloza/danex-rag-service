from pathlib import Path
import sys

import anyio
import pytest
from mcp import Client
from mcp.server.mcpserver.exceptions import ToolError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mcp_server

COMPLAINT_QUESTION = "W jakim terminie klient może zgłosić reklamację?"


@pytest.fixture(autouse=True)
def isolated_control_plane(tmp_path, monkeypatch):
    # The committed corpus, a throwaway database.
    monkeypatch.setattr(mcp_server, "DB_PATH", tmp_path / "control-plane-mcp.sqlite3")
    monkeypatch.setattr(mcp_server, "_ready_for", None)


def test_search_returns_lean_evidence_from_the_committed_corpus():
    response = mcp_server.search(COMPLAINT_QUESTION, limit=3)

    assert response["profile_version"] == "rag-2026.07-stable"
    assert response["channels"] == ["lexical"]
    assert response["query_id"].startswith("qry_")
    top = response["results"][0]
    assert top["source"] == "regulamin_salonu_2026.txt"
    assert set(top) == {"source", "rank", "score", "passage"}
    assert "reklamac" in top["passage"].lower()


def test_passage_is_whitespace_normalised_and_capped():
    ranked = [{"source": "big.txt", "rank": 1, "score": 1.0, "content": "word \n\n " * 1000}]

    [item] = mcp_server.evidence_for_agent(ranked)

    assert len(item["passage"]) == mcp_server.MAX_PASSAGE_CHARS
    assert "  " not in item["passage"] and "\n" not in item["passage"]


def test_limit_is_clamped_to_the_server_and_profile_bounds():
    assert len(mcp_server.search(COMPLAINT_QUESTION, limit=0)["results"]) == 1
    # The active profile's top_k (5) caps the fused list before the server's own maximum.
    assert len(mcp_server.search("salon klient wizyta usługi", limit=50)["results"]) <= 5


@pytest.mark.parametrize("question", ["", "   ", "x" * (mcp_server.MAX_QUESTION_CHARS + 1)])
def test_rejects_empty_and_oversized_questions(question):
    with pytest.raises(ToolError):
        mcp_server.search(question)


def test_trace_keeps_the_ranking_detail_the_agent_did_not_get():
    response = mcp_server.search(COMPLAINT_QUESTION, limit=2)

    trace = mcp_server.get_trace(response["query_id"])

    assert trace["route"] == "mcp_lexical"
    assert {stage["id"]: stage["status"] for stage in trace["stages"]}["dense"] == "skipped"
    assert trace["results"][0]["passage"] == response["results"][0]["passage"]
    assert "contributions" in trace["results"][0]


def test_unknown_trace_is_an_error():
    with pytest.raises(ToolError):
        mcp_server.get_trace("qry_missing")


def test_protocol_lists_read_only_tools_and_serves_search():
    async def scenario():
        async with Client(mcp_server.server) as client:
            tools = (await client.list_tools()).tools
            found = await client.call_tool("search", {"question": COMPLAINT_QUESTION, "limit": 1})
            missing = await client.call_tool("get_trace", {"query_id": "qry_missing"})
        return tools, found, missing

    tools, found, missing = anyio.run(scenario)

    assert {tool.name for tool in tools} == {"search", "get_trace"}
    assert all(tool.annotations.read_only_hint for tool in tools)
    assert not found.is_error
    assert found.structured_content["results"][0]["source"] == "regulamin_salonu_2026.txt"
    assert missing.is_error
