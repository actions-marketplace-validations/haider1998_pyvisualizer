"""Tests for `init` onboarding and the AGENTS.md / export --check wiring."""

import os
import tempfile

import pytest

from pyvisualizer.api import build_graph
from pyvisualizer.export import export_for_ai, export_would_change
from pyvisualizer.setup_init import run_init

_SRC = {
    "core.py": "def persist(record):\n    return record\n",
    "service.py": "from core import persist\n\ndef place(o):\n    return persist(o)\n",
}


@pytest.fixture
def project():
    tmp = tempfile.mkdtemp()
    for name, code in _SRC.items():
        with open(os.path.join(tmp, name), "w", encoding="utf-8") as f:
            f.write(code)
    with open(os.path.join(tmp, "pyproject.toml"), "w", encoding="utf-8") as f:
        f.write('[build-system]\nrequires = ["setuptools"]\n')
    return tmp


class TestInit:
    def test_list_writes_nothing(self, project):
        before = set(os.listdir(project))
        rc = run_init(project, list_only=True)
        assert rc == 0
        assert set(os.listdir(project)) == before

    def test_only_selected_profiles_are_created(self, project):
        rc = run_init(project, features="review", ci="github")
        assert rc == 0
        assert os.path.exists(os.path.join(project, ".github/workflows/pyvisualizer-review.yml"))
        # Not selected -> not created.
        assert not os.path.exists(os.path.join(project, ".github/workflows/pyvisualizer-check.yml"))
        with open(os.path.join(project, "pyproject.toml"), encoding="utf-8") as f:
            assert 'features = ["review"]' in f.read()

    def test_idempotent_skip_without_force(self, project):
        run_init(project, features="review", ci="github")
        wf = os.path.join(project, ".github/workflows/pyvisualizer-review.yml")
        with open(wf, "a", encoding="utf-8") as f:
            f.write("# edited\n")
        run_init(project, features="review", ci="github")
        with open(wf, encoding="utf-8") as f:
            assert "# edited" in f.read()  # not overwritten

    def test_force_overwrites(self, project):
        run_init(project, features="review", ci="github")
        wf = os.path.join(project, ".github/workflows/pyvisualizer-review.yml")
        with open(wf, "a", encoding="utf-8") as f:
            f.write("# edited\n")
        run_init(project, features="review", ci="github", force=True)
        with open(wf, encoding="utf-8") as f:
            assert "# edited" not in f.read()

    def test_context_profile_writes_artifacts(self, project):
        run_init(project, features="context", ci="none")
        assert os.path.exists(os.path.join(project, "ARCHITECTURE.json"))
        assert os.path.exists(os.path.join(project, "AGENTS.md"))

    def test_no_features_non_tty_errors(self, project):
        # features=None and not a TTY in the test harness -> error exit.
        assert run_init(project, features=None) == 1


class TestAgentsAndCheck:
    def test_agents_md_idempotent(self, project):
        result = build_graph(project)
        export_for_ai(result, out_dir=project, agents_md=True)
        agents = os.path.join(project, "AGENTS.md")
        with open(agents, encoding="utf-8") as f:
            first = f.read()
        export_for_ai(result, out_dir=project, agents_md=True)
        with open(agents, encoding="utf-8") as f:
            assert f.read() == first

    def test_export_check_detects_staleness(self, project):
        result = build_graph(project)
        assert export_would_change(result, out_dir=project) is True  # nothing written yet
        export_for_ai(result, out_dir=project, agents_md=True)
        assert export_would_change(result, out_dir=project) is False
        with open(os.path.join(project, "ARCHITECTURE.json"), "a", encoding="utf-8") as f:
            f.write("stale")
        assert export_would_change(result, out_dir=project) is True
