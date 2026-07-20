"""URL dispatch — the front door of a Django-style app. Every request path
enters here and fans out to a view (the shape `urlpatterns` produces)."""

from views import add_to_cart, checkout_view, order_detail, product_list


def dispatch(path, request):
    if path == "/products":
        return product_list(request)
    if path == "/cart/add":
        return add_to_cart(request)
    if path == "/checkout":
        return checkout_view(request)
    if path.startswith("/orders/"):
        return order_detail(request, path.split("/")[-1])
    return {"status": 404}
