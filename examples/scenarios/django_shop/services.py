"""Service layer — the business logic between views and models."""

from models import Cart, Order, Product


def list_products():
    return Product.all()


class CartService:
    def add(self, user, product_id):
        cart = Cart.for_user(user)
        cart.add_item(product_id)
        return cart

    def total(self, user):
        cart = Cart.for_user(user)
        return cart.subtotal()


class OrderService:
    def checkout(self, user):
        cart = Cart.for_user(user)
        total = cart.subtotal()
        order = Order.create(user, total)
        self._notify(order)
        return order

    def get(self, order_id):
        return Order.find(order_id)

    def _notify(self, order):
        return {"emailed": order}
