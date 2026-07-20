"""Infrastructure layer: persistence. The bottom of the stack; calls nothing
above it."""


class InvoiceRepository:
    def save(self, invoice):
        return self._write(invoice)

    def load(self, invoice_id):
        return self._read(invoice_id)

    def _write(self, invoice):
        return {"stored": invoice}

    def _read(self, invoice_id):
        return {"id": invoice_id, "amount": 100}
