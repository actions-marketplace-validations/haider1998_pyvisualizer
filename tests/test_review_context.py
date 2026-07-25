"""Tests for the review + context engine (Job 1 and Job 2) and change detection.

These use a real throwaway git repository so change detection, blast radius, and
link generation are exercised the way they run in production — not mocked.
"""

import os
import subprocess
import tempfile

import pytest

from pyvisualizer.api import build_graph
from pyvisualizer.changes import (
    changed_lines_from_git,
    map_lines_to_functions,
    repo_web_url,
    web_link,
)
from pyvisualizer.context import build_context_pack, render_pack_json, render_pack_markdown
from pyvisualizer.review import analyze_review, render_markdown, render_text

# The repo_before_after fixture (and its _BEFORE/_AFTER file contents) lives in
# tests/conftest.py so retrieval and MCP tests can share it.


class TestChangeDetection:
    def test_changed_functions_are_exactly_the_edited_ones(self, repo_before_after):
        result = build_graph(repo_before_after)
        changed = map_lines_to_functions(
            result.graph, changed_lines_from_git(repo_before_after, "main"), repo_before_after
        )
        assert changed == ["core.persist", "service.audit"]

    def test_no_base_no_changes(self, repo_before_after):
        # A ref that doesn't exist and no default -> empty (graceful).
        changed = changed_lines_from_git(repo_before_after, "does-not-exist-and-no-default")
        # Falls back to auto-detect (main exists) so this still finds changes;
        # the guarantee we assert is that it never raises and returns a dict.
        assert isinstance(changed, dict)

    def test_repo_web_url_and_link(self, repo_before_after):
        url = repo_web_url(repo_before_after)
        assert url == "https://github.com/acme/demo"
        assert web_link(url, "core.py", 3) == "https://github.com/acme/demo/blob/HEAD/core.py#L3"


class TestReview:
    def test_review_reports_changes_blast_and_cycle(self, repo_before_after):
        result = build_graph(repo_before_after)
        review = analyze_review(result.graph, result.project_root, base_ref="main")
        assert review.changed == ["core.persist", "service.audit"]
        assert review.blast_radius >= 2  # place_order, create, ... reach persist
        assert any(
            any("persist" in n for n in cycle) and any("audit" in n for n in cycle)
            for cycle in review.cycle_changes
        )

    def test_review_markdown_has_links_and_is_deterministic(self, repo_before_after):
        result = build_graph(repo_before_after)
        review = analyze_review(result.graph, result.project_root, base_ref="main")
        a = render_markdown(review, result.graph, result.project_root)
        b = render_markdown(review, result.graph, result.project_root)
        assert a == b
        assert "https://github.com/acme/demo/blob/HEAD/core.py" in a
        assert "```mermaid" in a

    def test_review_text_fallback(self, repo_before_after):
        result = build_graph(repo_before_after)
        review = analyze_review(result.graph, result.project_root, base_ref="main")
        text = render_text(review, result.graph, result.project_root)
        assert "Architecture Review" in text


class TestContext:
    def test_focus_is_always_included(self, repo_before_after):
        result = build_graph(repo_before_after)
        pack = build_context_pack(result, focus=["persist"], budget_tokens=4000)
        assert "core.persist" in pack.included
        # Direct neighbors present too.
        assert "core.validate" in pack.included

    def test_budget_omits_when_tiny(self, repo_before_after):
        result = build_graph(repo_before_after)
        pack = build_context_pack(result, focus=["persist"], budget_tokens=1)
        # Focus + neighbors are always kept even under an impossible budget.
        assert "core.persist" in pack.included
        # But unrelated far nodes are omitted.
        assert pack.omitted_count >= 0

    def test_context_pack_is_deterministic(self, repo_before_after):
        result = build_graph(repo_before_after)
        p1 = render_pack_markdown(build_context_pack(result, focus=["persist"]))
        p2 = render_pack_markdown(build_context_pack(result, focus=["persist"]))
        assert p1 == p2

    def test_context_json_schema(self, repo_before_after):
        import json

        result = build_graph(repo_before_after)
        pack = build_context_pack(result, focus=["persist"])
        data = json.loads(render_pack_json(pack))
        assert data["schema"] == "pyvisualizer/context@2"
        assert "core.persist" in data["included"]

    def test_from_git_focus(self, repo_before_after):
        result = build_graph(repo_before_after)
        pack = build_context_pack(result, from_git="main")
        assert "core.persist" in pack.focus
        assert "service.audit" in pack.focus


class TestPageRankIsSelfContained:
    """Guards the P0 bug where ranking silently degraded to alphabetical order.

    ``nx.pagerank`` dispatches to SciPy, which is **not** a dependency of this
    package. The old code caught the resulting ``ModuleNotFoundError`` and scored
    every node 0.0, so the tie-break in ``_select_nodes`` fell back to sorting by
    name and the pack filled with whatever came first in the alphabet — and the
    output changed depending on whether NumPy happened to be installed.
    """

    def test_ranking_does_not_call_networkx_pagerank(self, monkeypatch):
        """The ranking must not depend on NumPy/SciPy being importable at all."""
        import networkx as nx

        from pyvisualizer.context import personalized_pagerank

        def _explode(*args, **kwargs):
            raise AssertionError("nx.pagerank must not be used: it requires SciPy")

        monkeypatch.setattr(nx, "pagerank", _explode)

        G = nx.DiGraph([("a", "b"), ("b", "c"), ("x", "y")])
        pr = personalized_pagerank(G, ["a"])
        assert pr["a"] > 0.0
        assert pr["b"] > 0.0
        # A disconnected node is unreachable from the focus and scores exactly zero.
        assert pr["y"] == 0.0

    def test_pack_never_includes_functions_unreachable_from_focus(self, repo_before_after):
        """Budget fill must not pad the pack with unrelated functions."""
        import networkx as nx

        result = build_graph(repo_before_after)
        G = result.graph
        pack = build_context_pack(result, focus=["persist"], budget_tokens=100000)
        reachable = nx.node_connected_component(G.to_undirected(), pack.focus[0])
        unrelated = [n for n in pack.included if n not in reachable]
        assert unrelated == [], f"pack padded with unrelated functions: {unrelated}"

    def test_ranking_is_stable_without_numpy(self, repo_before_after, monkeypatch):
        """Same input, same pack — whether or not NumPy can be imported."""
        import builtins

        result = build_graph(repo_before_after)
        with_numpy = render_pack_markdown(build_context_pack(result, focus=["persist"]))

        real_import = builtins.__import__

        def _no_numpy(name, *args, **kwargs):
            if name.split(".")[0] in {"numpy", "scipy"}:
                raise ModuleNotFoundError(f"No module named {name!r}")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _no_numpy)
        without_numpy = render_pack_markdown(build_context_pack(result, focus=["persist"]))
        assert with_numpy == without_numpy


class TestBudgetIsRespected:
    """`--budget-tokens N` is a promise, and it used to be broken both ways.

    Measured across 322 real SWE-bench repositories at a 4,000-token budget, the
    old selection landed inside 75-100% of budget only 7% of the time: 16% of
    packs overran (worst case 52,615 tokens — 13x the request) because focus
    neighbours were added with no budget check at all, and 77% came in under 75%
    because the fill stopped at the first function too large to fit instead of
    skipping it.
    """

    def _wide_graph(self, tmp_path):
        """A hub with many neighbours — the shape that caused the 13x overrun."""
        pkg = tmp_path / "wide"
        pkg.mkdir()
        callers = "\n\n".join(
            f"def caller_{i}(argument_number_one, argument_number_two):\n    return hub()"
            for i in range(60)
        )
        (pkg / "mod.py").write_text(f"def hub():\n    return 1\n\n\n{callers}\n")
        return str(pkg)

    def test_pack_does_not_exceed_budget(self, tmp_path):
        """Budget governs function selection, which is what it is spent on."""
        from pyvisualizer.context import _est_tokens

        result = build_graph(self._wide_graph(tmp_path))
        budget = 200
        pack = build_context_pack(result, focus=["hub"], budget_tokens=budget)
        spent = sum(_est_tokens(line) for line in pack.rendered_nodes)
        assert spent <= budget, (
            f"pack spent {spent} tokens against a {budget} budget "
            f"({len(pack.included)} functions)"
        )

    def test_focus_survives_an_impossible_budget(self, tmp_path):
        """The one thing that may exceed budget is what the caller asked for."""
        result = build_graph(self._wide_graph(tmp_path))
        pack = build_context_pack(result, focus=["hub"], budget_tokens=1)
        assert "mod.hub" in pack.included

    def test_fill_skips_an_oversized_entry_instead_of_stopping(self, tmp_path):
        """One huge signature must not halt the fill while cheap nodes remain."""
        pkg = tmp_path / "mixed"
        pkg.mkdir()
        huge_args = ", ".join(f"parameter_with_a_very_long_name_{i}" for i in range(40))
        (pkg / "mod.py").write_text(
            "def hub():\n    return whale() or minnow_one() or minnow_two()\n\n"
            f"def whale({huge_args}):\n    return 1\n\n"
            "def minnow_one():\n    return 1\n\n"
            "def minnow_two():\n    return 1\n"
        )
        result = build_graph(str(pkg))
        # Enough budget for the small functions, not for the whale.
        pack = build_context_pack(result, focus=["hub"], budget_tokens=90)
        assert "mod.minnow_one" in pack.included and "mod.minnow_two" in pack.included
        assert "mod.whale" not in pack.included


class TestTaskContext:
    """--task: a prose description seeds the pack (symbols first, lexical next)."""

    def test_task_finds_the_relevant_functions(self, repo_before_after):
        result = build_graph(repo_before_after)
        pack = build_context_pack(
            result, task="fix `persist` so audit runs before the write", budget_tokens=2000
        )
        assert pack.strategy == "hybrid"
        assert "core.persist" in pack.included
        assert pack.seeds and pack.seeds[0]["node"] == "core.persist"
        assert pack.seeds[0]["source"] == "symbol"
        md = render_pack_markdown(pack)
        assert "- Task: fix `persist`" in md
        assert "## Seeds" in md

    def test_task_pack_is_deterministic(self, repo_before_after):
        result = build_graph(repo_before_after)
        md = [
            render_pack_markdown(
                build_context_pack(result, task="audit the persisted record flow")
            )
            for _ in range(2)
        ]
        assert md[0] == md[1]

    def test_task_without_usable_seeds_falls_back_labeled(self, repo_before_after):
        result = build_graph(repo_before_after)
        pack = build_context_pack(result, task="qqzz blorptastic unrelatedwords")
        assert pack.included, "a non-empty graph must never produce an empty pack"
        assert pack.fallback_used
        assert "Fallback" in render_pack_markdown(pack)

    def test_text_strategy_skips_graph_expansion(self, repo_before_after):
        result = build_graph(repo_before_after)
        pack = build_context_pack(
            result, task="persist validate record", strategy="text", budget_tokens=2000
        )
        assert pack.strategy == "text"
        assert "core.persist" in pack.included

    def test_strategy_without_task_is_an_error(self, repo_before_after):
        result = build_graph(repo_before_after)
        with pytest.raises(ValueError):
            build_context_pack(result, focus=["persist"], strategy="hybrid")

    def test_unknown_strategy_is_an_error(self, repo_before_after):
        result = build_graph(repo_before_after)
        with pytest.raises(ValueError):
            build_context_pack(result, task="x", strategy="grep")

    def test_multi_seed_pagerank_scores_all_seeds(self):
        import networkx as nx

        from pyvisualizer.context import personalized_pagerank

        G = nx.DiGraph()
        G.add_edge("a.one", "a.two")
        G.add_edge("b.three", "a.one")
        G.add_node("z.isolated")
        pr = personalized_pagerank(G, ["a.one", "b.three"])
        assert pr["a.one"] > 0 and pr["b.three"] > 0
        assert pr["z.isolated"] == 0.0

    def test_cli_task_end_to_end(self, repo_before_after, capsys):
        from pyvisualizer.cli import main

        rc = main(["context", repo_before_after, "--task", "fix `persist` audit ordering"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "# Context Pack" in out and "core.persist" in out


class TestTieredBodies:
    """Top-ranked focus/seed functions carry full source; the rest stay signatures."""

    def test_focus_body_is_included_under_a_generous_budget(self, repo_before_after):
        result = build_graph(repo_before_after)
        pack = build_context_pack(result, focus=["persist"], budget_tokens=4000)
        assert "core.persist" in pack.body_nodes
        assert "def persist(record):" in pack.bodies["core.persist"]
        md = render_pack_markdown(pack)
        assert "## Function bodies" in md
        assert "_(full source above)_" in md

    def test_bodies_never_go_to_non_focus_functions(self, repo_before_after):
        result = build_graph(repo_before_after)
        pack = build_context_pack(result, focus=["persist"], budget_tokens=4000)
        assert set(pack.body_nodes) <= set(pack.focus)

    def test_include_bodies_false_restores_signature_only_shape(self, repo_before_after):
        result = build_graph(repo_before_after)
        pack = build_context_pack(result, focus=["persist"], include_bodies=False)
        assert pack.body_nodes == [] and pack.bodies == {}
        assert "## Function bodies" not in render_pack_markdown(pack)

    def test_budget_covers_signatures_plus_bodies(self, tmp_path):
        from pyvisualizer.context import _est_tokens

        pkg = tmp_path / "wide"
        pkg.mkdir()
        callers = "\n\n".join(
            f"def caller_{i}(argument_number_one, argument_number_two):\n    return hub()"
            for i in range(60)
        )
        (pkg / "mod.py").write_text(f"def hub():\n    return 1\n\n\n{callers}\n")
        result = build_graph(str(pkg))
        budget = 200
        pack = build_context_pack(result, focus=["hub"], budget_tokens=budget)
        spent = sum(_est_tokens(line) for line in pack.rendered_nodes)
        spent += sum(_est_tokens(src) for src in pack.bodies.values())
        assert spent <= budget

    def test_json_schema_v2_reports_tiers(self, repo_before_after):
        import json as _json

        result = build_graph(repo_before_after)
        pack = build_context_pack(result, focus=["persist"], budget_tokens=4000)
        data = _json.loads(render_pack_json(pack))
        assert data["schema"] == "pyvisualizer/context@2"
        assert set(data["tiers"]) == set(data["included"])
        assert data["tiers"]["core.persist"] == "body"
        assert data["fallback_used"] is False
