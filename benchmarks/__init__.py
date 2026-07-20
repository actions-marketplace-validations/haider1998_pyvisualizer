"""Benchmark + validation harness for py-code-visualizer.

Everything here measures the real tool on real inputs and records the numbers
(with commit hash + hardware) into ``docs/benchmarks.json``. No number shown on
the website or in the docs is hand-written — it comes from :mod:`benchmarks.bench`.
"""
