"""Data ingestion."""


def load_dataset(source):
    rows = _read_rows(source)
    return _validate(rows)


def _read_rows(source):
    return [{"x": 1, "y": 0}]


def _validate(rows):
    return [r for r in rows if "y" in r]
