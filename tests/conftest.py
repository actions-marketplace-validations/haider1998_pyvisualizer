"""PyVisualizer test configuration."""

import os
import subprocess
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def sample_project_path():
    """Return path to the sample project."""
    return Path(__file__).parent.parent / "examples" / "sample_project"


@pytest.fixture
def temp_output_dir():
    """Create a temporary directory for test outputs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def simple_python_code():
    """Simple Python code for testing."""
    return """
class Calculator:
    def __init__(self):
        self.result = 0
    
    def add(self, a, b):
        self.result = a + b
        return self.result
    
    def subtract(self, a, b):
        self.result = a - b
        return self.result


def main():
    calc = Calculator()
    calc.add(1, 2)
    calc.subtract(5, 3)


if __name__ == "__main__":
    main()
"""


@pytest.fixture
def temp_python_file(temp_output_dir, simple_python_code):
    """Create a temporary Python file for testing."""
    file_path = temp_output_dir / "test_module.py"
    file_path.write_text(simple_python_code)
    return file_path


@pytest.fixture
def temp_python_package(temp_output_dir, simple_python_code):
    """Create a temporary Python package for testing."""
    package_dir = temp_output_dir / "test_package"
    package_dir.mkdir()

    # Create __init__.py
    (package_dir / "__init__.py").write_text("")

    # Create main module
    (package_dir / "main.py").write_text(simple_python_code)

    # Create another module
    (package_dir / "utils.py").write_text("""
def helper_function():
    return "helper"

class UtilClass:
    def util_method(self):
        return helper_function()
""")

    return package_dir


# --------------------------------------------------------------------------- #
# A real throwaway git repository (not mocks) — shared by review/context/
# retrieval/MCP tests so change detection and link generation are exercised the
# way they run in production.
# --------------------------------------------------------------------------- #

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
