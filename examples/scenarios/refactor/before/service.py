"""Service layer — several call paths converge on core.persist."""

from core import persist


def place_order(order):
    return persist(order)


def cancel_order(order_id):
    return persist({"cancel": order_id})


def audit(record):
    return {"audited": record}
