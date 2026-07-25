"""Tests for the MCP server's session cache and tool layer.

The tool layer is plain functions, so everything except the final FastMCP
wiring runs without the optional ``mcp`` SDK installed.
"""

import os
import sys

import pytest

from pyvisualizer.mcp_server import (
    ProjectSession,
    tool_context_pack,
    tool_impact,
    tool_search_code,
)


class TestProjectSession:
    def test_graph_and_index_are_cached(self, repo_before_after):
        session = ProjectSession(repo_before_after)
        g1, b1 = session.get()
        g2, b2 = session.get()
        assert g1 is g2 and b1 is b2

    def test_file_change_invalidates_the_cache(self, repo_before_after):
        session = ProjectSession(repo_before_after)
        g1, _ = session.get()
        core = os.path.join(repo_before_after, "core.py")
        with open(core, "a", encoding="utf-8") as f:
            f.write("\n\ndef newly_added():\n    return 42\n")
        g2, _ = session.get()
        assert g1 is not g2
        assert "core.newly_added" in g2.graph


class TestTools:
    def test_search_code_finds_functions(self, repo_before_after):
        session = ProjectSession(repo_before_after)
        out = tool_search_code(session, "persist record", k=5)
        assert "core.persist" in out and "core.py:" in out

    def test_search_code_no_match_is_helpful(self, repo_before_after):
        session = ProjectSession(repo_before_after)
        out = tool_search_code(session, "zzqx")
        assert "No functions matched" in out

    def test_context_pack_from_task(self, repo_before_after):
        session = ProjectSession(repo_before_after)
        out = tool_context_pack(session, task="fix `persist` audit ordering")
        assert out.startswith("# Context Pack")
        assert "core.persist" in out

    def test_context_pack_bad_strategy_is_readable(self, repo_before_after):
        session = ProjectSession(repo_before_after)
        out = tool_context_pack(session, strategy="text")  # text needs a task
        assert out.startswith("Cannot build pack:")

    def test_impact_known_symbol(self, repo_before_after):
        session = ProjectSession(repo_before_after)
        out = tool_impact(session, "persist")
        assert "Impact" in out and "place_order" in out

    def test_impact_unknown_symbol_suggests_closest(self, repo_before_after):
        session = ProjectSession(repo_before_after)
        out = tool_impact(session, "persistt")
        assert "not found" in out


@pytest.mark.skipif(sys.version_info < (3, 10), reason="mcp SDK needs Python 3.10+")
class TestServerWiring:
    def test_exactly_three_tools_are_registered(self, repo_before_after):
        mcp = pytest.importorskip("mcp")  # noqa: F841
        import asyncio

        from mcp.server.fastmcp import FastMCP

        from pyvisualizer.mcp_server import _register

        app = FastMCP("pyvisualizer-test")
        _register(app, ProjectSession(repo_before_after))
        tools = asyncio.run(app.list_tools())
        assert {t.name for t in tools} == {"search_code", "context_pack", "impact"}
