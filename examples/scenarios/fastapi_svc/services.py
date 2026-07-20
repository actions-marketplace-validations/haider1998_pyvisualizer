"""Service layer — orchestration between route handlers and repositories."""

from repos import InventoryRepo, OrderRepo


def list_orders(user):
    repo = OrderRepo()
    return repo.for_user(user)


class OrderFlow:
    def __init__(self):
        self.orders = OrderRepo()
        self.inventory = InventoryRepo()

    def place(self, payload):
        self.inventory.reserve(payload["sku"])
        order = self.orders.insert(payload)
        self._audit(order)
        return order

    def fetch(self, order_id):
        return self.orders.get(order_id)

    def _audit(self, order):
        return {"audited": order["id"]}
