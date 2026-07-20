"""Domain layer: business rules. It may call `infra` (down), but must NEVER
call `api` (up). One method here breaks that rule on purpose."""

from api.notifier import send_receipt
from infra.db import InvoiceRepository


class BillingService:
    def __init__(self):
        self.repo = InvoiceRepository()

    def charge(self, invoice):
        stored = self.repo.save(invoice)
        # VIOLATION: domain reaching back up into the api layer. This is the
        # exact call the gate must catch, with this file:line.
        send_receipt(stored)
        return stored

    def refund(self, invoice_id):
        # Clean: domain -> infra only.
        return self.repo.load(invoice_id)
