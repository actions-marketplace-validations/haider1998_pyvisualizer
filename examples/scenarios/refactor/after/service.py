"""Service layer AFTER the refactor: audit now persists an audit trail, which
is what closes the cycle back into core.persist."""

from core import persist


def place_order(order):
    return persist(order)


def cancel_order(order_id):
    return persist({"cancel": order_id})


def audit(record):
    # NEW: writes the audit record back through core.persist -> cycle.
    return persist({"audit": record})
