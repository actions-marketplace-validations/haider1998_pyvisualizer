"""Core persistence AFTER a refactor that added an audit hook — and quietly
introduced a circular dependency (persist -> audit -> persist)."""

from service import audit


def persist(record):
    validated = validate(record)
    audit(validated)  # NEW: this call closes a cycle with service.audit
    return _write(validated)


def validate(record):
    return _rules(record)


def _write(record):
    return {"stored": record}


def _rules(record):
    return record
