"""Data access. `Warehouse.fetch` is live; the CSV path is dead."""


class Warehouse:
    def fetch(self, period):
        return self._query(period)

    def _query(self, period):
        return [{"amount": 10, "period": period}]


def load_from_csv(path):
    """DEAD: an old ingestion path nothing calls anymore."""
    return _parse_csv_line(path)


def _parse_csv_line(line):
    """DEAD: only referenced by the dead load_from_csv."""
    return line.split(",")
