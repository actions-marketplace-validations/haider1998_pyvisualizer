"""API layer helper: outbound notifications."""


def send_receipt(invoice):
    return {"emailed": invoice}
