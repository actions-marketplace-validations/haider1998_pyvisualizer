"""Models — the persistence layer (Django-ORM shaped, plain Python)."""


class Product:
    @classmethod
    def all(cls):
        return [{"id": 1, "name": "widget"}]


class Cart:
    @classmethod
    def for_user(cls, user):
        return cls()

    def add_item(self, product_id):
        return self._save({"item": product_id})

    def subtotal(self):
        return 42

    def _save(self, row):
        return row


class Order:
    @classmethod
    def create(cls, user, total):
        return {"user": user, "total": total}

    @classmethod
    def find(cls, order_id):
        return {"id": order_id}
