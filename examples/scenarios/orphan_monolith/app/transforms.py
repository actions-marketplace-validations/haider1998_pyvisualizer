"""Row transforms. `summarize` calls a bare `clean()` that two modules define,
so that edge is genuinely ambiguous — the tool flags it instead of guessing."""

from app.helpers import scrub


def normalize(rows):
    return [scrub(r) for r in rows]


def summarize(rows):
    total = 0
    for r in rows:
        # `clean` is defined in BOTH app.helpers and app.legacy with different
        # behavior, and neither is imported here — resolution is ambiguous.
        r = clean(r)  # noqa: F821  (intentionally unresolved for the demo)
        total += r.get("amount", 0)
    return {"total": total, "count": len(rows)}
