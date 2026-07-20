"""Core persistence — the function everyone is afraid to touch."""


def persist(record):
    validated = validate(record)
    return _write(validated)


def validate(record):
    return _rules(record)


def _write(record):
    return {"stored": record}


def _rules(record):
    return record
