"""Tests for the call-graph truth engine: accuracy, confidence, determinism."""

import os
import tempfile

import pytest

from pyvisualizer.core.graph import build_call_graph
from pyvisualizer.core.model import (
    CONFIDENCE_AMBIGUOUS,
    CONFIDENCE_INHERITED,
    CONFIDENCE_RESOLVED,
)
from pyvisualizer.utils.file_discovery import (
    analyze_project,
    find_project_python_files,
)


def _build_from_sources(sources: dict):
    """Write ``{filename: code}`` to a temp dir and return the call graph."""
    tmp = tempfile.mkdtemp()
    for name, code in sources.items():
        path = os.path.join(tmp, name)
        os.makedirs(os.path.dirname(path), exist_ok=True) if os.path.dirname(name) else None
        with open(path, "w", encoding="utf-8") as f:
            f.write(code)
    files = find_project_python_files(tmp)
    analyzers, calls = analyze_project(files, tmp)
    return build_call_graph(analyzers, calls), tmp


def _edge(G, caller_suffix, callee_suffix):
    for s, t, d in G.edges(data=True):
        if s.endswith(caller_suffix) and t.endswith(callee_suffix):
            return d
    return None


class TestNestedDefinitions:
    def test_nested_function_is_a_node(self):
        G, _ = _build_from_sources(
            {"m.py": ("def outer():\n" "    def inner():\n" "        pass\n" "    return inner\n")}
        )
        names = set(G.nodes())
        assert any(n.endswith("outer") for n in names)
        assert any("<locals>.inner" in n for n in names)

    def test_nested_class_qualified_name(self):
        G, _ = _build_from_sources(
            {
                "m.py": (
                    "class Outer:\n"
                    "    class Inner:\n"
                    "        def deep(self):\n"
                    "            pass\n"
                )
            }
        )
        assert any(n.endswith("Outer.Inner.deep") for n in G.nodes())


class TestChainedCalls:
    def test_inner_call_of_chain_is_captured(self):
        # get_client() is a module function; its inner call must be recorded
        # even though it is the receiver of a further .fetch() attribute call.
        G, _ = _build_from_sources(
            {
                "m.py": (
                    "def get_client():\n"
                    "    return object()\n"
                    "def use():\n"
                    "    get_client().fetch()\n"
                )
            }
        )
        assert _edge(G, "use", "get_client") is not None


class TestConfidenceTagging:
    def test_ambiguous_call_is_flagged_not_fabricated(self):
        # Two classes define save(); a call on an untyped receiver must be
        # tagged ambiguous with both candidates preserved -- never silently
        # resolved to one.
        G, _ = _build_from_sources(
            {
                "m.py": (
                    "class A:\n"
                    "    def save(self):\n"
                    "        pass\n"
                    "class B:\n"
                    "    def save(self):\n"
                    "        pass\n"
                    "def run(x):\n"
                    "    x.save()\n"
                )
            }
        )
        edge = _edge(G, "run", "save")
        assert edge is not None
        assert edge["confidence"] == CONFIDENCE_AMBIGUOUS
        assert len(edge["candidates"]) == 2

    def test_no_edge_for_external_calls(self):
        # Calls to stdlib / builtins must not invent edges.
        G, _ = _build_from_sources(
            {"m.py": ("import os\n" "def run():\n" "    os.getcwd()\n" "    print('hi')\n")}
        )
        assert G.number_of_edges() == 0

    def test_typed_parameter_resolves_method(self):
        G, _ = _build_from_sources(
            {
                "svc.py": ("class Client:\n" "    def fetch(self):\n" "        pass\n"),
                "app.py": ("from svc import Client\n" "def run(c: Client):\n" "    c.fetch()\n"),
            }
        )
        edge = _edge(G, "app.run", "Client.fetch")
        assert edge is not None
        assert edge["confidence"] == CONFIDENCE_RESOLVED

    def test_edge_has_provenance(self):
        G, _ = _build_from_sources({"m.py": ("def a():\n" "    b()\n" "def b():\n" "    pass\n")})
        edge = _edge(G, "m.a", "m.b")
        assert edge is not None
        assert edge["lineno"] == 2
        assert edge["file"].endswith("m.py")


class TestInheritance:
    def test_super_call_marked_inherited(self):
        G, _ = _build_from_sources(
            {
                "m.py": (
                    "class Base:\n"
                    "    def run(self):\n"
                    "        pass\n"
                    "class Child(Base):\n"
                    "    def run(self):\n"
                    "        super().run()\n"
                )
            }
        )
        edge = _edge(G, "Child.run", "Base.run")
        assert edge is not None
        assert edge["confidence"] == CONFIDENCE_INHERITED

    def test_inherited_method_via_self(self):
        G, _ = _build_from_sources(
            {
                "m.py": (
                    "class Base:\n"
                    "    def helper(self):\n"
                    "        pass\n"
                    "class Child(Base):\n"
                    "    def run(self):\n"
                    "        self.helper()\n"
                )
            }
        )
        edge = _edge(G, "Child.run", "Base.helper")
        assert edge is not None
        assert edge["confidence"] == CONFIDENCE_INHERITED


class TestDeterminism:
    def test_two_runs_are_identical(self):
        sources = {
            "a.py": "from b import B\ndef main():\n    B().go()\n",
            "b.py": "class B:\n    def go(self):\n        self.step()\n    def step(self):\n        pass\n",
        }
        G1, tmp = _build_from_sources(sources)

        files = find_project_python_files(tmp)
        analyzers, calls = analyze_project(files, tmp)
        G2 = build_call_graph(analyzers, calls)

        def sig(G):
            lines = [f"N {n}" for n in sorted(G.nodes())]
            lines += [
                f"E {s}|{t}|{d.get('confidence')}|{d.get('lineno')}"
                for s, t, d in sorted(G.edges(data=True))
            ]
            return "\n".join(lines)

        assert sig(G1) == sig(G2)
