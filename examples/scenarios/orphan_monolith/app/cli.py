"""Entry point of the reporting service. Everything live starts here."""

from app.pipeline import ReportPipeline
from app.storage import Warehouse


def run(period):
    """The one function a new hire is told to read first."""
    warehouse = Warehouse()
    pipeline = ReportPipeline(warehouse)
    report = pipeline.build(period)
    return pipeline.render(report)


def main():
    return run("2026-Q3")
