"""API layer: HTTP entry points. Calls down into the domain layer (allowed)."""

from domain.billing import BillingService


class BillingController:
    def __init__(self):
        self.service = BillingService()

    def post_charge(self, request):
        return self.service.charge(request)

    def post_refund(self, request):
        return self.service.refund(request["id"])
