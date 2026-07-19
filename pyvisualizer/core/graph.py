"""
Function call graph construction.

This module provides the FunctionCallVisitor for extracting function calls
and building a call graph from analyzed Python modules.

Core principle — *Ground Truth, never guesswork*:
    Every edge carries a ``confidence`` (resolved / inherited / ambiguous) and a
    ``file:line`` provenance. Calls that could match several definitions are
    tagged ``ambiguous`` with the full candidate list preserved — we never
    silently pick one and present it as fact. Calls to code outside the project
    (stdlib, third-party) produce no edge rather than an invented one.
"""

import ast
import logging
from typing import Any, Dict, List, NamedTuple, Optional, Set

import networkx as nx

from pyvisualizer.core.analyzer import ModuleAnalyzer
from pyvisualizer.core.model import (
    CONFIDENCE_AMBIGUOUS,
    CONFIDENCE_INHERITED,
    CONFIDENCE_RESOLVED,
)

logger = logging.getLogger("pyvisualizer.graph")

# Resolution mechanisms that are eligible for a project-wide short-name
# fallback when the primary resolution did not land on a known node.
_FALLBACK_VIA = {"name", "attr", "self-fallback"}


class Resolution(NamedTuple):
    """The outcome of resolving a single call expression."""

    target: Optional[str] = None  # best-effort qualified/partial target
    exact: bool = False  # target is a verified project node
    via: str = ""  # mechanism: import/self/typed-var/class/super/name/attr...
    base: bool = False  # resolved through a base class (inheritance)
    external: bool = False  # resolves outside the project -> emit no edge


class FunctionCallVisitor(ast.NodeVisitor):
    """AST visitor to extract function calls with provenance and confidence."""

    def __init__(
        self,
        module_name: str,
        file_path: str,
        module_analyzer: ModuleAnalyzer,
        all_modules: Dict[str, ModuleAnalyzer],
        all_module_names: Set[str],
    ):
        self.current_function: Optional[str] = None
        self.current_class: Optional[str] = None
        self.class_stack: List[str] = []
        self.function_stack: List[str] = []
        self.module_name = module_name
        self.file_path = file_path
        self.module_analyzer = module_analyzer
        self.all_modules = all_modules
        self.all_module_names = all_module_names
        self.calls: List[Dict[str, Any]] = []
        self.class_instances: Dict[str, str] = {}  # var name -> class name
        self.current_class_vars: Dict[str, str] = {}  # 'self.x' -> class name
        self.context_managers: Dict[str, str] = {}

        self._class_cache: Dict[str, Optional[str]] = {}

    # ------------------------------------------------------------------ scopes
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        previous_class = self.current_class
        if self.class_stack:
            self.current_class = f"{self.class_stack[-1]}.{node.name}"
        else:
            self.current_class = f"{self.module_name}.{node.name}"

        self.class_stack.append(self.current_class)
        previous_vars = self.current_class_vars
        self.current_class_vars = {}

        self.generic_visit(node)

        self.class_stack.pop()
        self.current_class = previous_class
        self.current_class_vars = previous_vars

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function_common(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function_common(node)

    def _visit_function_common(self, node: Any) -> None:
        parent_func = self.current_function

        if self.class_stack:
            self.current_function = f"{self.class_stack[-1]}.{node.name}"
        else:
            self.current_function = f"{self.module_name}.{node.name}"

        self.function_stack.append(self.current_function)

        # Scope local variable typing to this function body so a name in one
        # function never leaks into a sibling.
        saved_instances = self.class_instances
        self.class_instances = dict(saved_instances)
        self._seed_param_types(node)

        for decorator in node.decorator_list:
            self.visit(decorator)

        self.generic_visit(node)

        self.class_instances = saved_instances
        self.function_stack.pop()
        self.current_function = parent_func if self.function_stack else None

    def _seed_param_types(self, node: Any) -> None:
        """Seed variable typing from annotated parameters (e.g. ``x: Client``)."""
        info = self.module_analyzer.functions.get(self.current_function or "")
        if not info:
            return
        for arg_name, ann in info.get("arg_types", {}).items():
            cls = self._annotation_class(ann)
            if cls:
                self.class_instances[arg_name] = cls

    @staticmethod
    def _annotation_class(ann: Any) -> Optional[str]:
        if not isinstance(ann, dict):
            return None
        if ann.get("type") == "name":
            return ann.get("name")
        if ann.get("type") == "subscript":
            return ann.get("container")
        return None

    # ------------------------------------------------------------ assignments
    def visit_Assign(self, node: ast.Assign) -> None:
        if isinstance(node.value, ast.Call):
            class_name = self._extract_call_target(node.value)
            for target in node.targets:
                if isinstance(target, ast.Name):
                    if class_name:
                        self.class_instances[target.id] = class_name
                elif isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                    if target.value.id == "self" and self.current_class:
                        if class_name:
                            self.current_class_vars[f"self.{target.attr}"] = class_name
        elif isinstance(node.value, ast.Tuple):
            for i, elt in enumerate(node.value.elts):
                if isinstance(elt, ast.Call):
                    class_name = self._extract_call_target(elt)
                    if class_name and i < len(node.targets):
                        target = node.targets[i]
                        if isinstance(target, ast.Name):
                            self.class_instances[target.id] = class_name
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name) and node.annotation:
            annotation = self._process_annotation(node.annotation)
            if annotation:
                self.class_instances[node.target.id] = annotation
        if node.value and isinstance(node.value, ast.Call):
            class_name = self._extract_call_target(node.value)
            if class_name and isinstance(node.target, ast.Name):
                self.class_instances[node.target.id] = class_name
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            if isinstance(item.context_expr, ast.Call):
                class_name = self._extract_call_target(item.context_expr)
                if item.optional_vars and isinstance(item.optional_vars, ast.Name):
                    if class_name:
                        self.context_managers[item.optional_vars.id] = class_name
                        self.class_instances[item.optional_vars.id] = class_name
        self.generic_visit(node)

    # ----------------------------------------------------------------- calls
    def visit_Call(self, node: ast.Call) -> None:
        if self.current_function:
            res = self._resolve_call(node)
            if res.target and not res.external:
                self.calls.append(
                    {
                        "caller": self.current_function,
                        "lineno": node.lineno,
                        "res": res,
                    }
                )
        # Recurse into the *entire* call expression: the callee expression
        # (so chained calls like get_client().fetch() capture the inner call),
        # arguments, keywords, comprehensions and lambdas.
        self.generic_visit(node)

    def _resolve_call(self, node: ast.Call) -> Resolution:
        # --- bare name: func_name() --------------------------------------
        if isinstance(node.func, ast.Name):
            func_name = node.func.id

            if func_name in self.module_analyzer.imports.import_map:
                imported_path = self.module_analyzer.imports.import_map[func_name]
                if "." in imported_path:
                    module_path, short = imported_path.rsplit(".", 1)
                    found = self._lookup_module_function(module_path, short)
                    if found:
                        return Resolution(found, exact=True, via="import")
                    # Import resolves outside the project: no edge.
                    return Resolution(imported_path, via="import", external=True)
                return Resolution(imported_path, via="import", external=True)

            local_target = f"{self.module_name}.{func_name}"
            if local_target in self.module_analyzer.functions:
                return Resolution(local_target, exact=True, via="local")

            # A locally instantiated class used as a callable? (rare) -> skip.
            # Otherwise defer to a project-wide short-name lookup.
            return Resolution(func_name, via="name")

        # --- attribute call: obj.method() --------------------------------
        if isinstance(node.func, ast.Attribute):
            value = node.func.value
            method_name = node.func.attr

            # super().method()
            if self._is_super_call(value) and self.current_class:
                found = self._find_method_in_hierarchy(
                    self.current_class, method_name, start_at_base=True
                )
                if found:
                    return Resolution(found, exact=True, via="super", base=True)
                return Resolution(None)

            if isinstance(value, ast.Name):
                obj_name = value.id

                # self.method()
                if obj_name == "self" and self.current_class:
                    found = self._find_method_in_hierarchy(self.current_class, method_name)
                    if found:
                        base = not found.startswith(self.current_class + ".")
                        return Resolution(found, exact=True, via="self", base=base)
                    return Resolution(method_name, via="self-fallback")

                # variable with a known class: obj.method()
                if obj_name in self.class_instances:
                    class_q = self._resolve_class_name(self.class_instances[obj_name])
                    if class_q:
                        found = self._find_method_in_hierarchy(class_q, method_name)
                        if found:
                            base = not found.startswith(class_q + ".")
                            return Resolution(found, exact=True, via="typed-var", base=base)
                    return Resolution(method_name, via="attr")

                # ClassName.method()  (static/class methods, direct class ref)
                class_q = self._resolve_class_name(obj_name)
                if class_q:
                    found = self._find_method_in_hierarchy(class_q, method_name)
                    if found:
                        base = not found.startswith(class_q + ".")
                        return Resolution(found, exact=True, via="class", base=base)

                # module.function()
                if obj_name in self.module_analyzer.imports.import_map:
                    module_path = self.module_analyzer.imports.import_map[obj_name]
                    found = self._lookup_module_function(module_path, method_name)
                    if found:
                        return Resolution(found, exact=True, via="import")
                    return Resolution(f"{module_path}.{method_name}", via="import", external=True)

                if obj_name in self.context_managers:
                    class_q = self._resolve_class_name(self.context_managers[obj_name])
                    if class_q:
                        found = self._find_method_in_hierarchy(class_q, method_name)
                        if found:
                            return Resolution(found, exact=True, via="context")
                    return Resolution(method_name, via="attr")

                # Unknown object type: eligible for a *unique-only* fallback.
                return Resolution(method_name, via="attr")

            # nested attribute: pkg.mod.function()
            if isinstance(value, ast.Attribute):
                parts = self._extract_attribute_chain(node.func)
                if len(parts) >= 2:
                    obj_path = ".".join(parts[:-1])
                    found = self._lookup_module_function(obj_path, parts[-1])
                    if found:
                        return Resolution(found, exact=True, via="import")
                    return Resolution(f"{obj_path}.{parts[-1]}", via="attr")

            # method call on a call result: get_client().fetch()
            # The inner call is captured by generic_visit; the outer method's
            # receiver type is unknown, so allow a unique-only fallback.
            if isinstance(value, ast.Call):
                return Resolution(method_name, via="attr")

        return Resolution(None)

    @staticmethod
    def _is_super_call(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "super"
        )

    def _lookup_module_function(self, module_path: str, func_name: str) -> Optional[str]:
        """Find ``module_path.func_name`` among project modules, if present."""
        for m_name, analyzer in self.all_modules.items():
            if m_name == module_path or m_name.endswith("." + module_path):
                target = f"{m_name}.{func_name}"
                if target in analyzer.functions:
                    return target
        return None

    def _lookup_class(self, class_q: str) -> Optional[Dict[str, Any]]:
        for analyzer in self.all_modules.values():
            info = analyzer.classes.get(class_q)
            if info:
                return info
        return None

    def _find_method_in_hierarchy(
        self, class_q: str, method_name: str, start_at_base: bool = False
    ) -> Optional[str]:
        """Resolve ``method_name`` on ``class_q`` through its MRO.

        Returns the qualified target if found (in the class or any resolvable
        ancestor), else ``None``. When ``start_at_base`` is set the class
        itself is skipped (used for ``super()``).
        """
        visited: Set[str] = set()
        queue: List[str] = []
        if start_at_base:
            info = self._lookup_class(class_q)
            if info:
                for b in info.get("bases", []):
                    bq = self._resolve_class_name(b)
                    if bq:
                        queue.append(bq)
        else:
            queue.append(class_q)

        while queue:
            cq = queue.pop(0)
            if cq in visited:
                continue
            visited.add(cq)
            info = self._lookup_class(cq)
            if not info:
                continue
            if method_name in info["methods"]:
                return f"{cq}.{method_name}"
            for b in info.get("bases", []):
                bq = self._resolve_class_name(b)
                if bq and bq not in visited:
                    queue.append(bq)
        return None

    def _resolve_class_name(self, class_name: str) -> Optional[str]:
        if class_name in self._class_cache:
            return self._class_cache[class_name]

        result: Optional[str] = None
        for analyzer in self.all_modules.values():
            if class_name in analyzer.classes:
                result = class_name
                break
        if result is None and class_name in self.module_analyzer.imports.import_map:
            imported = self.module_analyzer.imports.import_map[class_name]
            # Only accept if it names a known project class.
            for analyzer in self.all_modules.values():
                if imported in analyzer.classes:
                    result = imported
                    break
                # Try short-name match at tail.
                for cq in analyzer.classes:
                    if cq.endswith("." + imported.split(".")[-1]):
                        result = cq
                        break
                if result:
                    break
        if result is None:
            local_class = f"{self.module_name}.{class_name}"
            if local_class in self.module_analyzer.classes:
                result = local_class
        if result is None:
            # Match by bare class short-name across the project (last resort).
            short = class_name.split(".")[-1]
            for analyzer in self.all_modules.values():
                for cq, cinfo in analyzer.classes.items():
                    if cinfo["name"] == short:
                        result = cq
                        break
                if result:
                    break

        self._class_cache[class_name] = result
        return result

    def _extract_call_target(self, call_node: ast.Call) -> Optional[str]:
        if isinstance(call_node.func, ast.Name):
            target_name = call_node.func.id
            if target_name in self.module_analyzer.imports.import_map:
                return self.module_analyzer.imports.import_map[target_name]
            local_class = f"{self.module_name}.{target_name}"
            if local_class in self.module_analyzer.classes:
                return local_class
            return target_name
        if isinstance(call_node.func, ast.Attribute):
            parts = self._extract_attribute_chain(call_node.func)
            return ".".join(parts) if parts else None
        return None

    def _extract_attribute_chain(self, node: ast.AST) -> List[str]:
        if isinstance(node, ast.Name):
            return [node.id]
        if isinstance(node, ast.Attribute):
            return self._extract_attribute_chain(node.value) + [node.attr]
        return []

    def _process_annotation(self, node: ast.AST) -> Optional[str]:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            parts = self._extract_attribute_chain(node)
            return ".".join(parts) if parts else None
        if isinstance(node, ast.Subscript):
            if isinstance(node.value, ast.Name):
                return node.value.id
            if isinstance(node.value, ast.Attribute):
                parts = self._extract_attribute_chain(node.value)
                return ".".join(parts) if parts else None
        return None


def _short_name(qualified: str) -> str:
    return qualified.split(".")[-1]


def _disambiguate(caller: str, matches: List[str]) -> List[str]:
    """Narrow a list of same-short-name candidates using caller context.

    Returns a list: a single element means we disambiguated confidently;
    more than one means the call is genuinely ambiguous.
    """
    if len(matches) <= 1:
        return list(matches)

    caller_parts = caller.split(".")
    caller_module = caller_parts[0] if caller_parts else ""
    caller_class = ".".join(caller_parts[:-1]) if len(caller_parts) >= 3 else None

    # 1. same class as the caller
    if caller_class:
        same_class = [m for m in matches if ".".join(m.split(".")[:-1]) == caller_class]
        if len(same_class) == 1:
            return same_class

    # 2. same module as the caller
    same_module = [m for m in matches if m.startswith(caller_module + ".")]
    if len(same_module) == 1:
        return same_module

    # Still ambiguous.
    return sorted(matches)


def build_call_graph(
    module_analyzers: Dict[str, ModuleAnalyzer], all_calls: List[Dict[str, Any]]
) -> nx.DiGraph:
    """Build a directed call graph with confidence-tagged, sourced edges."""
    G = nx.DiGraph()

    # Nodes (added in deterministic order).
    for module_name in sorted(module_analyzers):
        analyzer = module_analyzers[module_name]
        for func_name in sorted(analyzer.functions):
            func_info = analyzer.functions[func_name]
            G.add_node(
                func_name,
                **{
                    "name": func_info["name"],
                    "module": module_name,
                    "class": func_info.get("class"),
                    "lineno": func_info.get("lineno", 0),
                    "end_lineno": func_info.get("end_lineno"),
                    "path": analyzer.file_path,
                    "is_async": func_info.get("is_async", False),
                    "is_property": func_info.get("is_property", False),
                    "is_static": func_info.get("is_static", False),
                    "is_classmethod": func_info.get("is_classmethod", False),
                    "is_method": func_info.get("is_method", False),
                    "is_nested": func_info.get("is_nested", False),
                    "decorators": func_info.get("decorators", []),
                    "decorator_names": func_info.get("decorator_names", []),
                    "args": func_info.get("args", []),
                },
            )

    # Short-name lookup for project-wide fallback resolution.
    function_lookup: Dict[str, List[str]] = {}
    for func_name in G.nodes:
        function_lookup.setdefault(_short_name(func_name), []).append(func_name)
    for key in function_lookup:
        function_lookup[key].sort()

    # File lookup for edge provenance.
    node_file = {n: G.nodes[n].get("path", "") for n in G.nodes}

    # Deterministic edge processing: aggregate then emit sorted.
    edges: Dict[tuple, Dict[str, Any]] = {}

    def _consider(
        caller: str,
        callee: str,
        lineno: int,
        confidence: str,
        via: str,
        candidates: Optional[List[str]] = None,
    ) -> None:
        key = (caller, callee)
        existing = edges.get(key)
        if existing is None:
            edges[key] = {
                "lineno": lineno,
                "confidence": confidence,
                "via": via,
                "candidates": candidates or [],
                "file": node_file.get(caller, ""),
            }
        else:
            # Prefer the highest-confidence explanation; keep earliest line.
            from pyvisualizer.core.model import CONFIDENCE_ORDER

            if CONFIDENCE_ORDER[confidence] < CONFIDENCE_ORDER[existing["confidence"]]:
                existing["confidence"] = confidence
                existing["via"] = via
                existing["candidates"] = candidates or []
            existing["lineno"] = min(existing["lineno"], lineno)

    for call in all_calls:
        caller = call["caller"]
        res: Resolution = call["res"]
        lineno = call["lineno"]
        target = res.target
        if caller not in G or target is None:
            continue

        # Exact hit on a known node.
        if res.exact and target in G:
            conf = CONFIDENCE_INHERITED if res.base else CONFIDENCE_RESOLVED
            _consider(caller, target, lineno, conf, res.via)
            continue

        # Fallback-eligible: resolve by project-wide short name.
        if res.via in _FALLBACK_VIA:
            short = _short_name(target)
            matches = function_lookup.get(short, [])
            if not matches:
                continue  # external / builtin -> no invented edge
            narrowed = _disambiguate(caller, matches)
            if len(narrowed) == 1:
                _consider(caller, narrowed[0], lineno, CONFIDENCE_RESOLVED, res.via + "-unique")
            else:
                representative = narrowed[0]
                _consider(
                    caller,
                    representative,
                    lineno,
                    CONFIDENCE_AMBIGUOUS,
                    res.via,
                    candidates=narrowed,
                )
            continue

        # exact target that isn't a project node, or external -> no edge.

    for caller, callee in sorted(edges):
        data = edges[(caller, callee)]
        G.add_edge(caller, callee, **data)

    _mark_cycles(G)
    return G


def _mark_cycles(G: nx.DiGraph) -> None:
    """Flag edges that participate in a dependency cycle (deterministically)."""
    try:
        for cycle in nx.simple_cycles(G):
            for i in range(len(cycle)):
                source = cycle[i]
                target = cycle[(i + 1) % len(cycle)]
                if G.has_edge(source, target):
                    G.edges[source, target]["is_cycle"] = True
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(f"Could not detect cycles: {e}")
