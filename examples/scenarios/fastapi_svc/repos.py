"""Repository layer — persistence access, the bottom of the stack."""


class OrderRepo:
    def for_user(self, user):
        return self._query({"user": user})

    def insert(self, payload):
        return self._write(payload)

    def get(self, order_id):
        return self._query({"id": order_id})

    def _query(self, where):
        return {"id": 1, **where}

    def _write(self, row):
        return {"id": 1, **row}


class InventoryRepo:
    def reserve(self, sku):
        return self._write({"sku": sku, "reserved": True})

    def _write(self, row):
        return row
