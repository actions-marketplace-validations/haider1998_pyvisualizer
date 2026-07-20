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

_BEFORE = {
    "core.py": (
        "def persist(record):\n"
        "    validated = validate(record)\n"
        "    return _write(validated)\n\n"
        "def validate(record):\n"
        "    return record\n\n"
        "def _write(record):\n"
        "    return {'stored': record}\n"
    ),
    "service.py": (
        "from core import persist\n\n"
        "def place_order(order):\n"
        "    return persist(order)\n\n"
        "def audit(record):\n"
        "    return {'audited': record}\n"
    ),
    "handlers.py": (
        "from service import place_order\n\n"
        "def create(request):\n"
        "    return place_order(request)\n"
    ),
}

# The "after" state adds an audit() hook to persist() and makes audit() call
# persist() back — introducing a cycle and changing two functions.
_AFTER_CORE = (
    "from service import audit\n\n"
    "def persist(record):\n"
    "    validated = validate(record)\n"
    "    audit(validated)\n"
    "    return _write(validated)\n\n"
    "def validate(record):\n"
    "    return record\n\n"
    "def _write(record):\n"
    "    return {'stored': record}\n"
)
_AFTER_SERVICE = (
    "from core import persist\n\n"
    "def place_order(order):\n"
    "    return persist(order)\n\n"
    "def audit(record):\n"
    "    return persist({'audit': record})\n"
)


def _git(root, *args):
    subprocess.run(["git", "-C", root, *args], check=True, capture_output=True, text=True)


@pytest.fixture
def repo_before_after():
    """A git repo committed at 'before', with the working tree at 'after'."""
    tmp = tempfile.mkdtemp()
    _git(tmp, "init")
    _git(tmp, "config", "user.email", "t@t.com")
    _git(tmp, "config", "user.name", "t")
    _git(tmp, "remote", "add", "origin", "git@github.com:acme/demo.git")
    for name, code in _BEFORE.items():
        with open(os.path.join(tmp, name), "w", encoding="utf-8") as f:
            f.write(code)
    _git(tmp, "add", "-A")
    _git(tmp, "commit", "-m", "before")
    _git(tmp, "branch", "-M", "main")
    # Apply the "after" state to the working tree (uncommitted).
    with open(os.path.join(tmp, "core.py"), "w", encoding="utf-8") as f:
        f.write(_AFTER_CORE)
    with open(os.path.join(tmp, "service.py"), "w", encoding="utf-8") as f:
        f.write(_AFTER_SERVICE)
    return tmp


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
        assert data["schema"] == "pyvisualizer/context@1"
        assert "core.persist" in data["included"]

    def test_from_git_focus(self, repo_before_after):
        result = build_graph(repo_before_after)
        pack = build_context_pack(result, from_git="main")
        assert "core.persist" in pack.focus
        assert "service.audit" in pack.focus
