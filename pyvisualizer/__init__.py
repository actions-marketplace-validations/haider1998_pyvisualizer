"""
PyVisualizer - Python Code Architecture Visualization Tool

Transform complex Python codebases into stunning, interactive architectural diagrams.
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

try:
    __version__ = _pkg_version("py-code-visualizer")
except PackageNotFoundError:  # pragma: no cover - running from a source tree
    __version__ = "0.0.0.dev0"

__author__ = "Syed Mohd Haider Rizvi"
__email__ = "smhrizvi281@gmail.com"

from pyvisualizer.api import GraphResult, build_graph
from pyvisualizer.core.analyzer import ImportCollector, ImportInfo, ModuleAnalyzer
from pyvisualizer.core.graph import FunctionCallVisitor, build_call_graph
from pyvisualizer.utils.file_discovery import find_project_python_files, get_module_name

__all__ = [
    "ImportInfo",
    "ImportCollector",
    "ModuleAnalyzer",
    "FunctionCallVisitor",
    "build_call_graph",
    "build_graph",
    "GraphResult",
    "find_project_python_files",
    "get_module_name",
    "__version__",
]
