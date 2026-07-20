"""The live report pipeline. Reachable from cli.run."""

from app.storage import Warehouse
from app.transforms import normalize, summarize


class ReportPipeline:
    def __init__(self, warehouse: Warehouse):
        self.warehouse = warehouse

    def build(self, period):
        rows = self.warehouse.fetch(period)
        clean = normalize(rows)
        return summarize(clean)

    def render(self, report):
        return self._format(report)

    def _format(self, report):
        return "\n".join(f"{k}: {v}" for k, v in report.items())
