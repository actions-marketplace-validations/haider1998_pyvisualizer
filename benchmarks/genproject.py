"""
Deterministic synthetic-project generator for benchmarking.

Given a seed, this emits a byte-identical Python project every time: a layered
set of packages whose functions and methods call one another through patterns
the analyzer actually resolves (local scope, imports, ``self``, inheritance),
plus a controlled sprinkling of genuinely ambiguous calls so the confidence
breakdown the benchmark reports is realistic rather than staged.

Nothing here is imported or executed by py-code-visualizer — the generated tree
is only ever read as text and parsed with ``ast``. This module is
pure-stdlib on purpose so it can run anywhere.

Usage::

    python -m benchmarks.genproject /tmp/bench_project --target-lines 100000
"""

from __future__ import annotations

import argparse
import os
import random
import shutil
from typing import List

# Layers are ordered; a module in layer i may only import from layers > i.
# That keeps the generated architecture acyclic and realistic (no random
# spaghetti), which makes the health/cycle numbers meaningful too.
LAYERS = ["api", "service", "domain", "repository", "util"]


def _module_name(layer: str, idx: int) -> str:
    return f"mod_{layer}_{idx:03d}"


def _class_name(layer: str, idx: int, cidx: int) -> str:
    return f"{layer.capitalize()}Comp{idx:03d}_{cidx}"


def _gen_module(
    rng: random.Random,
    pkg: str,
    layer: str,
    idx: int,
    lower_targets: List[str],
    funcs_per_module: int,
    classes_per_module: int,
) -> str:
    """Render one module's source as a deterministic string."""
    lines: List[str] = []
    lines.append('"""Auto-generated benchmark module (deterministic)."""')
    lines.append("")

    # Import a couple of lower-layer modules so cross-module edges resolve.
    imports = rng.sample(lower_targets, k=min(len(lower_targets), 2)) if lower_targets else []
    for imp in imports:
        lines.append(f"from {imp} import entry as {imp.split('.')[-1]}_entry")
    if imports:
        lines.append("")

    # A small pool of module-level helper functions that call each other and
    # the imported entry points (resolved edges).
    helper_names = [f"helper_{idx:03d}_{i}" for i in range(funcs_per_module)]
    for i, hname in enumerate(helper_names):
        lines.append(f"def {hname}(value):")
        body: List[str] = []
        # Call a sibling helper (local-scope resolution).
        if i > 0 and rng.random() < 0.7:
            sib = helper_names[rng.randint(0, i - 1)]
            body.append(f"    value = {sib}(value)")
        # Call an imported entry (import resolution).
        if imports and rng.random() < 0.6:
            imp = rng.choice(imports)
            body.append(f"    value = {imp.split('.')[-1]}_entry(value)")
        body.append("    return value + 1")
        lines.extend(body)
        lines.append("")

    # Classes with methods that call self.<method> (self resolution) and one
    # inheritance chain per module (super() -> inherited edges).
    prev_class = None
    for cidx in range(classes_per_module):
        cname = _class_name(layer, idx, cidx)
        base = f"({prev_class})" if prev_class and rng.random() < 0.5 else ""
        lines.append(f"class {cname}{base}:")
        method_names = [f"step_{cidx}_{m}" for m in range(rng.randint(2, 4))]
        for mi, mname in enumerate(method_names):
            lines.append(f"    def {mname}(self, value):")
            mbody: List[str] = []
            if mi > 0 and rng.random() < 0.7:
                sib = method_names[rng.randint(0, mi - 1)]
                mbody.append(f"        value = self.{sib}(value)")
            if base and mi == 0 and rng.random() < 0.6:
                # Inherited call through MRO.
                mbody.append("        value = super().run(value)")
            if helper_names and rng.random() < 0.5:
                mbody.append(f"        value = {rng.choice(helper_names)}(value)")
            mbody.append("        return value")
            lines.extend(mbody)
        # A stable entry method every class shares (gives super().run a target).
        lines.append("    def run(self, value):")
        lines.append(f"        return self.{method_names[0]}(value)")
        lines.append("")
        prev_class = cname

    # The lowest layer ("util") defines a function under a name that is shared
    # across many util modules. When an upper-layer helper calls that bare name
    # WITHOUT importing it, the short-name lookup finds multiple candidates and
    # the edge is (correctly) tagged ``ambiguous`` — never fabricated. This
    # gives the confidence breakdown a real third category.
    if layer == "util":
        lines.append("def common_task(value):")
        lines.append(f"    return value + {idx}")
        lines.append("")
    elif helper_names and rng.random() < 0.4:
        # Upper-layer helper calls the shared name with no import -> ambiguous.
        extra = helper_names[0]
        # Re-render the first helper to include the ambiguous call.
        marker = f"def {extra}(value):"
        insert_at = lines.index(marker) + 1
        lines.insert(insert_at, "    value = common_task(value)")

    # A module-level ``entry`` that other modules import and call.
    lines.append("def entry(value):")
    if helper_names:
        lines.append(f"    return {helper_names[0]}(value)")
    else:
        lines.append("    return value")
    lines.append("")

    return "\n".join(lines)


def generate(
    out_dir: str,
    *,
    seed: int = 1998,
    target_lines: int = 100_000,
    funcs_per_module: int = 6,
    classes_per_module: int = 3,
) -> dict:
    """Generate the project tree; return a small stats dict.

    The generator keeps adding modules (round-robin across layers) until the
    total emitted line count reaches ``target_lines``, so the size is
    reproducible for a given ``target_lines`` regardless of machine.
    """
    rng = random.Random(seed)
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    pkg_root = os.path.join(out_dir, "genproj")
    os.makedirs(pkg_root)
    open(os.path.join(pkg_root, "__init__.py"), "w").close()
    for layer in LAYERS:
        ldir = os.path.join(pkg_root, layer)
        os.makedirs(ldir)
        open(os.path.join(ldir, "__init__.py"), "w").close()

    total_lines = 0
    n_modules = 0
    per_layer_idx = {layer: 0 for layer in LAYERS}
    # Track already-emitted lower-layer modules so imports point at real files.
    emitted: dict = {layer: [] for layer in LAYERS}

    layer_cycle = 0
    while total_lines < target_lines:
        layer = LAYERS[layer_cycle % len(LAYERS)]
        layer_cycle += 1
        idx = per_layer_idx[layer]
        per_layer_idx[layer] += 1

        lower_layers = LAYERS[LAYERS.index(layer) + 1 :]
        lower_targets = [m for ll in lower_layers for m in emitted[ll]]

        src = _gen_module(
            rng, "genproj", layer, idx, lower_targets, funcs_per_module, classes_per_module
        )
        mod_name = _module_name(layer, idx)
        path = os.path.join(pkg_root, layer, f"{mod_name}.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write(src)
        emitted[layer].append(f"genproj.{layer}.{mod_name}")
        total_lines += src.count("\n") + 1
        n_modules += 1

    return {
        "out_dir": out_dir,
        "package_root": pkg_root,
        "seed": seed,
        "modules": n_modules,
        "lines": total_lines,
        "layers": len(LAYERS),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate a deterministic synthetic Python project.")
    ap.add_argument("out_dir", help="Directory to (re)create the project in.")
    ap.add_argument("--seed", type=int, default=1998)
    ap.add_argument("--target-lines", type=int, default=100_000)
    args = ap.parse_args()
    stats = generate(args.out_dir, seed=args.seed, target_lines=args.target_lines)
    print(
        f"Generated {stats['modules']} modules "
        f"(~{stats['lines']:,} lines) in {stats['package_root']}"
    )


if __name__ == "__main__":
    main()
