"""
PyVisualizer CLI — deterministic architecture ground truth for Python.

Subcommands
    visualize   Render a diagram (html | mermaid | json | svg | png)
    readme      Inject/update a Mermaid diagram inside a Markdown file
    json        Emit the canonical graph JSON
    diff        Compare two graph JSON snapshots (PR-ready report)
    check       Enforce architecture rules (layers, cycles) — CI gate
    impact      Blast-radius analysis for a function

Back-compat: ``py-code-visualizer <path> [options]`` still works and maps to
the ``visualize`` subcommand.
"""

import argparse
import logging
import os
import sys
from typing import TYPE_CHECKING, List, Optional

from pyvisualizer import __version__

if TYPE_CHECKING:
    import networkx as nx

    from pyvisualizer.api import GraphResult
    from pyvisualizer.diff import DiffResult

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("pyvisualizer")

_SUBCOMMANDS = {
    "visualize",
    "readme",
    "json",
    "diff",
    "check",
    "impact",
    "export",
    "health",
    "review",
    "context",
    "init",
}


# --------------------------------------------------------------------------- #
# Argument parsing
# --------------------------------------------------------------------------- #
def _inject_default_subcommand(argv: List[str]) -> List[str]:
    """Preserve the legacy ``<path> [options]`` form by defaulting to visualize."""
    if not argv:
        return ["visualize"]
    first = argv[0]
    if first in _SUBCOMMANDS:
        return argv
    if first in ("-h", "--help", "--version"):
        return argv
    return ["visualize"] + argv


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="py-code-visualizer",
        description="Deterministic architecture ground truth for Python projects.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    def _common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--modules", "-m", nargs="+", help="Include only these modules")
        p.add_argument("--exclude", "-x", nargs="+", help="Exclude module patterns")
        p.add_argument("--depth", "-d", type=int, help="Max call depth from entry")
        p.add_argument("--entry", "-e", help="Entry point (module.function)")
        p.add_argument("--max-nodes", type=int, default=150, help="Max nodes")
        p.add_argument(
            "--strict", action="store_true", help="Drop ambiguous edges (no guesses at all)"
        )
        p.add_argument("--project-name", "-p", help="Project name for titles")
        p.add_argument("--verbose", "-v", action="store_true")

    # visualize -----------------------------------------------------------
    pv = sub.add_parser("visualize", help="Render a diagram")
    pv.add_argument("path", help="Path to Python project or file")
    pv.add_argument("--output", "-o", help="Output file path")
    pv.add_argument(
        "--format", "-f", choices=["html", "mermaid", "json", "c4", "svg", "png"], default="html"
    )
    pv.add_argument(
        "--churn",
        action="store_true",
        help="Overlay git change-frequency (heatmap) in the HTML viewer",
    )
    _common(pv)
    pv.set_defaults(func=cmd_visualize)

    # readme --------------------------------------------------------------
    pr = sub.add_parser("readme", help="Self-heal a Mermaid diagram in a Markdown file")
    pr.add_argument("path", nargs="?", default=".", help="Project path")
    pr.add_argument("--target", "-t", help="Markdown file to update (default: README.md)")
    pr.add_argument("--detail", choices=["module", "class", "function"], help="Diagram granularity")
    pr.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if the file would change (CI drift gate)",
    )
    pr.add_argument(
        "--no-links",
        action="store_true",
        help="Omit the collapsed 'Jump to source' index below the diagram",
    )
    _common(pr)
    pr.set_defaults(func=cmd_readme)

    # json ----------------------------------------------------------------
    pj = sub.add_parser("json", help="Emit canonical graph JSON")
    pj.add_argument("path", help="Project path")
    pj.add_argument("--output", "-o", help="Output file (default: stdout)")
    _common(pj)
    pj.set_defaults(func=cmd_json)

    # diff ----------------------------------------------------------------
    pd = sub.add_parser("diff", help="Diff two graph JSON snapshots")
    pd.add_argument("base", help="Base graph JSON")
    pd.add_argument("head", help="Head graph JSON")
    pd.add_argument("--format", choices=["markdown", "text"], default="markdown")
    pd.add_argument("--output", "-o", help="Output file (default: stdout)")
    pd.add_argument("--project-name", "-p", default="")
    pd.add_argument(
        "--fail-on-new-cycles",
        action="store_true",
        help="Exit non-zero if new circular dependencies appear",
    )
    pd.add_argument("--no-diagram", action="store_true")
    pd.add_argument("--verbose", "-v", action="store_true")
    pd.set_defaults(func=cmd_diff)

    # check ---------------------------------------------------------------
    pc = sub.add_parser("check", help="Enforce architecture rules (CI gate)")
    pc.add_argument("path", nargs="?", default=".", help="Project path")
    pc.add_argument("--fail-on-cycles", action="store_true", help="Fail on any circular dependency")
    pc.add_argument("--forbid", nargs="+", help="Ad-hoc layer rules, e.g. 'domain -> api'")
    pc.add_argument("--layers", nargs="+", help="Layer names")
    _common(pc)
    pc.set_defaults(func=cmd_check)

    # impact --------------------------------------------------------------
    pi = sub.add_parser("impact", help="Blast-radius analysis for a function")
    pi.add_argument("target", help="Function (short or qualified name)")
    pi.add_argument("path", nargs="?", default=".", help="Project path")
    pi.add_argument(
        "--format", "-f", choices=["text", "markdown"], default="text", help="Output format"
    )
    _common(pi)
    pi.set_defaults(func=cmd_impact)

    # check gains a dead-code flag.
    pc.add_argument(
        "--dead-code", action="store_true", help="Report functions with no in-project callers"
    )

    # health --------------------------------------------------------------
    ph = sub.add_parser("health", help="Architecture health score (A–F)")
    ph.add_argument("path", nargs="?", default=".", help="Project path")
    ph.add_argument("--badge", help="Write a self-contained SVG badge to this path")
    ph.add_argument("--min-grade", help="Fail if grade is below this (e.g. B-)")
    _common(ph)
    ph.set_defaults(func=cmd_health)

    # export --------------------------------------------------------------
    pe = sub.add_parser("export", help="Export ground truth for AI tools")
    pe.add_argument("path", nargs="?", default=".", help="Project path")
    pe.add_argument(
        "--for-ai",
        action="store_true",
        default=True,
        help="Emit ARCHITECTURE.json + ARCHITECTURE.md",
    )
    pe.add_argument("--out-dir", "-o", default=".", help="Output directory")
    pe.add_argument(
        "--no-agents-md",
        action="store_true",
        help="Do not add a py-code-visualizer section to AGENTS.md",
    )
    pe.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if the exported files would change (CI freshness gate)",
    )
    _common(pe)
    pe.set_defaults(func=cmd_export)

    # review --------------------------------------------------------------
    prv = sub.add_parser("review", help="PR review report: what changed + blast radius")
    prv.add_argument("path", nargs="?", default=".", help="Project path")
    prv.add_argument("--base", help="Base git ref to diff against (default: auto-detect)")
    prv.add_argument(
        "--format", "-f", choices=["markdown", "text"], default="markdown", help="Output format"
    )
    prv.add_argument("--output", "-o", help="Output file (default: stdout)")
    prv.add_argument(
        "--fail-above",
        type=int,
        help="Exit non-zero if the blast radius exceeds this many callers (policy, off by default)",
    )
    _common(prv)
    prv.set_defaults(func=cmd_review)

    # context -------------------------------------------------------------
    pctx = sub.add_parser("context", help="Task-scoped verified context pack for AI agents")
    pctx.add_argument("path", nargs="?", default=".", help="Project path")
    pctx.add_argument("--focus", nargs="+", help="Function/class/file names to center the pack on")
    pctx.add_argument("--from-git", dest="from_git", help="Center on functions changed vs this ref")
    pctx.add_argument(
        "--budget-tokens", type=int, default=4000, help="Approx token budget for the pack"
    )
    pctx.add_argument("--output", "-o", help="Markdown output file (default: stdout)")
    pctx.add_argument("--json", dest="json_out", help="Also write the machine-readable pack JSON")
    _common(pctx)
    pctx.set_defaults(func=cmd_context)

    # init ----------------------------------------------------------------
    pin = sub.add_parser("init", help="Set up only the automation you want (opt-in)")
    pin.add_argument("path", nargs="?", default=".", help="Project path")
    pin.add_argument(
        "--with",
        dest="features",
        help="Comma-separated: review,readme,context,gates (skips the prompt)",
    )
    pin.add_argument(
        "--ci", choices=["github", "gitlab", "none"], default="github", help="CI provider"
    )
    pin.add_argument(
        "--list", action="store_true", help="Show what each profile creates; write nothing"
    )
    pin.add_argument("--force", action="store_true", help="Overwrite existing generated files")
    pin.set_defaults(func=cmd_init)

    return parser


def _configure_logging(args: argparse.Namespace) -> None:
    if getattr(args, "verbose", False):
        logging.getLogger("pyvisualizer").setLevel(logging.DEBUG)


def main(args: Optional[list] = None) -> int:
    argv = list(sys.argv[1:] if args is None else args)
    argv = _inject_default_subcommand(argv)
    parser = _build_parser()
    parsed = parser.parse_args(argv)
    _configure_logging(parsed)
    if not hasattr(parsed, "func"):
        parser.print_help()
        return 1
    try:
        return int(parsed.func(parsed))
    except (FileNotFoundError, ValueError) as e:
        logger.error(str(e))
        return 1


# --------------------------------------------------------------------------- #
# Subcommand handlers
# --------------------------------------------------------------------------- #
def _build(args: argparse.Namespace, *, full: bool = False) -> "GraphResult":
    from pyvisualizer.api import build_graph

    # Analysis commands (review, context) must see the whole graph — trimming to
    # ``max_nodes`` is a visualization concern and would silently drop the very
    # functions being analyzed, breaking blast radius and focus resolution.
    max_nodes = None if full else getattr(args, "max_nodes", None)
    return build_graph(
        args.path,
        modules=getattr(args, "modules", None),
        exclude=getattr(args, "exclude", None),
        entry=getattr(args, "entry", None),
        depth=getattr(args, "depth", None),
        max_nodes=max_nodes,
        strict=getattr(args, "strict", False),
        project_name=getattr(args, "project_name", None),
    )


def cmd_visualize(args: argparse.Namespace) -> int:
    from pyvisualizer.serializers.json_graph import graph_to_json
    from pyvisualizer.visualizers.d3 import generate_d3_visualization
    from pyvisualizer.visualizers.mermaid import (
        create_interactive_html,
        generate_styled_mermaid,
    )

    result = _build(args)
    G = result.graph
    if G.number_of_nodes() == 0:
        logger.warning("No functions to visualize after applying filters")
        return 0

    fmt = args.format
    output = args.output or f"{result.project_name}_visualization.{fmt}"
    out_dir = os.path.dirname(os.path.abspath(output))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    if getattr(args, "churn", False):
        from pyvisualizer.overlays import apply_churn

        if apply_churn(G, result.project_root):
            logger.info("Applied git churn overlay.")
        else:
            logger.warning("No churn data (not a git repo?); overlay skipped.")

    if fmt == "html":
        generate_d3_visualization(
            G,
            output,
            result.project_name,
            project_root=result.project_root,
            tool_version=__version__,
        )
    elif fmt == "c4":
        from pyvisualizer.serializers.c4 import generate_c4_dsl

        with open(output, "w", encoding="utf-8") as f:
            f.write(generate_c4_dsl(G, result.project_name))
        logger.info("Structurizr C4 DSL saved to %s", output)
    elif fmt == "json":
        with open(output, "w", encoding="utf-8") as f:
            f.write(
                graph_to_json(
                    G,
                    project_name=result.project_name,
                    project_root=result.project_root,
                    tool_version=__version__,
                )
            )
        logger.info("JSON graph saved to %s", output)
    elif fmt == "mermaid":
        code = generate_styled_mermaid(G)
        with open(output, "w", encoding="utf-8") as f:
            f.write(code)
        html_path = f"{os.path.splitext(output)[0]}.html"
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(create_interactive_html(code, result.project_name))
        logger.info("Mermaid saved to %s (HTML: %s)", output, html_path)
    elif fmt in ("svg", "png"):
        _render_graphviz(G, output, result.project_name, fmt)
    return 0


def _render_graphviz(G: "nx.DiGraph", output: str, project_name: str, fmt: str) -> None:
    try:
        import graphviz
    except ImportError:
        logger.error("graphviz is required for %s output (pip install graphviz).", fmt)
        from pyvisualizer.visualizers.d3 import generate_d3_visualization

        generate_d3_visualization(G, f"{os.path.splitext(output)[0]}.html", project_name)
        return

    colors = {
        "constructor": "#E53935",
        "property": "#FF6D00",
        "async": "#AA00FF",
        "private": "#757575",
        "method": "#2962FF",
        "function": "#00C853",
    }
    dot = graphviz.Digraph(
        comment=f"{project_name} Code Structure",
        engine="dot",
        format=fmt,
        graph_attr={"rankdir": "LR", "bgcolor": "transparent", "fontname": "Arial"},
    )
    for node in sorted(G.nodes()):
        nd = G.nodes[node]
        name = node.split(".")[-1]
        if name in ("__init__", "__new__"):
            fill = colors["constructor"]
        elif nd.get("is_property"):
            fill = colors["property"]
        elif nd.get("is_async"):
            fill = colors["async"]
        elif name.startswith("_") and not name.startswith("__"):
            fill = colors["private"]
        elif nd.get("class"):
            fill = colors["method"]
        else:
            fill = colors["function"]
        dot.node(
            node,
            label=name,
            shape="box" if nd.get("class") else "ellipse",
            style="filled",
            fillcolor=fill,
            fontcolor="white",
            fontname="Arial",
        )
    for s, t, d in sorted(G.edges(data=True)):
        if d.get("is_cycle"):
            dot.edge(s, t, color="#F44336", style="dashed")
        else:
            dot.edge(s, t, color="#616161")
    dot.render(output, cleanup=True)
    logger.info("%s saved to %s.%s", fmt.upper(), output, fmt)


def _source_index_markdown(G: "nx.DiGraph", base_dir: str) -> str:
    """A collapsed <details> index of every function as a relative source link.

    Relative markdown links (``pkg/mod.py#L42``) resolve natively on GitHub when
    the diagram lives in a README, giving reviewers one-click jump-to-source with
    no absolute URLs and no dependence on a remote. Deterministic (sorted).
    """
    rows: List[str] = []
    for node in sorted(G.nodes()):
        data = G.nodes[node]
        path = data.get("path", "")
        lineno = int(data.get("lineno", 0) or 0)
        if not path:
            continue
        try:
            rel = os.path.relpath(os.path.realpath(path), os.path.realpath(base_dir)).replace(
                os.sep, "/"
            )
        except ValueError:
            continue
        anchor = f"#L{lineno}" if lineno else ""
        rows.append(f"- [`{node}`]({rel}{anchor})")
    if not rows:
        return ""
    return (
        "<details>\n<summary>📍 Jump to source ("
        + str(len(rows))
        + " functions)</summary>\n\n"
        + "\n".join(rows)
        + "\n</details>"
    )


def cmd_readme(args: argparse.Namespace) -> int:
    from pyvisualizer.config import load_config
    from pyvisualizer.inject import inject, update_file
    from pyvisualizer.visualizers.mermaid import generate_github_mermaid

    cfg = load_config(args.path)
    # CLI flags override config; config overrides built-in defaults.
    if args.exclude is None and cfg.exclude:
        args.exclude = cfg.exclude
    if args.modules is None and cfg.modules:
        args.modules = cfg.modules
    if getattr(args, "max_nodes", None) in (None, 150) and cfg.max_nodes:
        args.max_nodes = cfg.max_nodes
    if not getattr(args, "strict", False):
        args.strict = cfg.strict
    detail = args.detail or cfg.detail
    target = args.target or cfg.target

    from pyvisualizer.metrics import compute_health

    result = _build(args)
    G = result.graph
    mermaid_code = generate_github_mermaid(G, detail=detail)
    health = compute_health(G)

    heading = (
        f"*{G.number_of_nodes()} functions · {G.number_of_edges()} calls · "
        f"health {health.grade} ({health.score}/100) — detail: {detail}*"
    )
    footer = (
        "<sub>🔒 Deterministic, AST-verified — no code executed. "
        "Generated by [py-code-visualizer]"
        "(https://github.com/haider1998/PyVisualizer).</sub>"
    )

    target_path = (
        target
        if os.path.isabs(target)
        else os.path.join(
            (
                os.path.abspath(args.path)
                if os.path.isdir(args.path)
                else os.path.dirname(os.path.abspath(args.path))
            ),
            target,
        )
    )

    if not getattr(args, "no_links", False):
        index = _source_index_markdown(G, os.path.dirname(target_path))
        if index:
            footer = footer + "\n\n" + index

    if getattr(args, "check", False):
        existing = ""
        if os.path.exists(target_path):
            with open(target_path, "r", encoding="utf-8") as f:
                existing = f.read()
        _, changed = inject(existing, mermaid_code, heading=heading, footer=footer)
        if changed:
            logger.error("%s is out of date. Run `py-code-visualizer readme`.", target)
            return 1
        logger.info("%s architecture diagram is up to date.", target)
        return 0

    changed = update_file(target_path, mermaid_code, heading=heading, footer=footer)
    if changed:
        logger.info("Updated architecture diagram in %s", target_path)
    else:
        logger.info("%s already up to date (no change).", target_path)
    return 0


def cmd_json(args: argparse.Namespace) -> int:
    from pyvisualizer.serializers.json_graph import graph_to_json

    result = _build(args)
    payload = graph_to_json(
        result.graph,
        project_name=result.project_name,
        project_root=result.project_root,
        tool_version=__version__,
    )
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(payload)
        logger.info("JSON graph saved to %s", args.output)
    else:
        print(payload)
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    from pyvisualizer.diff import DiffResult, diff_graphs, render_markdown
    from pyvisualizer.serializers.json_graph import load_graph_json

    base = load_graph_json(args.base)
    head = load_graph_json(args.head)
    result: DiffResult = diff_graphs(base, head)

    if args.format == "markdown":
        out = render_markdown(result, args.project_name, include_diagram=not args.no_diagram)
    else:
        out = _diff_text(result)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(out)
    else:
        print(out)

    if args.fail_on_new_cycles and result.new_cycles:
        logger.error("%d new circular dependency(ies) introduced.", len(result.new_cycles))
        return 2
    return 0


def _diff_text(result: "DiffResult") -> str:
    lines = [
        f"Added functions:   {len(result.added_functions)}",
        f"Removed functions: {len(result.removed_functions)}",
        f"Added calls:       {len(result.added_edges)}",
        f"Removed calls:     {len(result.removed_edges)}",
        f"New cycles:        {len(result.new_cycles)}",
    ]
    for c in result.new_cycles:
        lines.append("  cycle: " + " -> ".join(n.split(".")[-1] for n in c))
    return "\n".join(lines)


def cmd_check(args: argparse.Namespace) -> int:
    from pyvisualizer.config import Rules, load_config
    from pyvisualizer.gates import check_layer_rules, cycle_violations, render_report

    cfg = load_config(args.path)
    rules: Rules = cfg.rules
    if args.forbid:
        rules = Rules(
            layers=args.layers or rules.layers,
            forbid=args.forbid,
            allow_ambiguous=rules.allow_ambiguous,
        )

    result = _build(args)
    G = result.graph

    layer_v = check_layer_rules(G, rules)
    cycle_v = cycle_violations(G) if args.fail_on_cycles else []

    print(render_report(layer_v, cycle_v))

    if getattr(args, "dead_code", False):
        from pyvisualizer.metrics import find_dead_code

        dead = find_dead_code(G)
        if dead:
            print(
                f"\n🟡 {len(dead)} function(s) with no in-project callers "
                "(review — may be public API):"
            )
            for d in dead:
                print(f"    {d}")
    return 1 if (layer_v or cycle_v) else 0


def cmd_health(args: argparse.Namespace) -> int:
    from pyvisualizer.metrics import badge_svg, compute_health, render_health

    result = _build(args)
    report = compute_health(result.graph)
    print(render_health(report, result.project_name))

    if args.badge:
        with open(args.badge, "w", encoding="utf-8") as f:
            f.write(badge_svg(report))
        logger.info("Health badge written to %s", args.badge)

    if args.min_grade:
        # Grades sort lexicographically the wrong way; compare scores instead.
        order = ["F", "D-", "D", "D+", "C-", "C", "C+", "B-", "B", "B+", "A-", "A", "A+"]
        try:
            if order.index(report.grade) < order.index(args.min_grade):
                logger.error("Health grade %s is below required %s.", report.grade, args.min_grade)
                return 1
        except ValueError:
            logger.warning("Unknown --min-grade %s", args.min_grade)
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    from pyvisualizer.export import export_for_ai, export_would_change

    result = _build(args, full=True)
    agents_md = not getattr(args, "no_agents_md", False)
    if getattr(args, "check", False):
        changed = export_would_change(
            result, out_dir=args.out_dir, tool_version=__version__, agents_md=agents_md
        )
        if changed:
            logger.error("AI export is stale — run `py-code-visualizer export` to refresh.")
            return 1
        logger.info("AI export is up to date.")
        return 0
    paths = export_for_ai(
        result, out_dir=args.out_dir, tool_version=__version__, agents_md=agents_md
    )
    extra = f" and {paths['agents']}" if "agents" in paths else ""
    logger.info("Wrote %s, %s%s", paths["json"], paths["markdown"], extra)
    return 0


def cmd_impact(args: argparse.Namespace) -> int:
    from pyvisualizer.impact import analyze_impact, render_markdown, render_text

    result = _build(args, full=True)
    impact = analyze_impact(result.graph, args.target)
    if getattr(args, "format", "text") == "markdown":
        print(render_markdown(impact, result.graph, result.project_root))
    else:
        print(render_text(impact))
    return 0 if impact.found else 1


def cmd_review(args: argparse.Namespace) -> int:
    from pyvisualizer.review import analyze_review, render_markdown, render_text

    result = _build(args, full=True)
    review = analyze_review(result.graph, result.project_root, base_ref=args.base)
    if args.format == "markdown":
        report = render_markdown(review, result.graph, result.project_root)
    else:
        report = render_text(review, result.graph, result.project_root)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report + "\n")
        logger.info("Review report written to %s", args.output)
    else:
        print(report)

    if args.fail_above is not None and review.blast_radius > args.fail_above:
        logger.error(
            "Blast radius %d exceeds --fail-above %d", review.blast_radius, args.fail_above
        )
        return 1
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    from pyvisualizer.context import build_context_pack, render_pack_json, render_pack_markdown

    result = _build(args, full=True)
    pack = build_context_pack(
        result,
        focus=getattr(args, "focus", None),
        from_git=getattr(args, "from_git", None),
        budget_tokens=args.budget_tokens,
    )
    markdown = render_pack_markdown(pack)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(markdown + "\n")
        logger.info("Context pack written to %s", args.output)
    else:
        print(markdown)
    if getattr(args, "json_out", None):
        with open(args.json_out, "w", encoding="utf-8") as f:
            f.write(render_pack_json(pack))
        logger.info("Context pack JSON written to %s", args.json_out)
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    from pyvisualizer.setup_init import run_init

    return run_init(
        args.path,
        features=getattr(args, "features", None),
        ci=args.ci,
        list_only=args.list,
        force=args.force,
    )


if __name__ == "__main__":
    sys.exit(main())
