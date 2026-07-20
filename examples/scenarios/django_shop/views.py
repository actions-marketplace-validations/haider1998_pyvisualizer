"""Views — thin request handlers that delegate to the service layer."""

from services import CartService, OrderService, list_products


def product_list(request):
    return {"products": list_products()}


def add_to_cart(request):
    cart = CartService()
    cart.add(request["user"], request["product_id"])
    return {"status": 200}


def checkout_view(request):
    orders = OrderService()
    order = orders.checkout(request["user"])
    return {"order": order}


def order_detail(request, order_id):
    orders = OrderService()
    return {"order": orders.get(order_id)}
