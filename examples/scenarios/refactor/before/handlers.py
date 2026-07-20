"""HTTP handlers — the top of the call paths that reach core.persist."""

from service import cancel_order, place_order


class OrderHandler:
    def create(self, request):
        return place_order(request)

    def cancel(self, request):
        return cancel_order(request["id"])
