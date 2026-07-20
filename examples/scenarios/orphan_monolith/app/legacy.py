"""An old module a departed contractor left behind. Its `clean` is the second
candidate that makes `summarize`'s bare `clean()` ambiguous. `archive` is dead."""


def clean(row):
    # Different behavior from helpers.clean — which is exactly why guessing
    # one of them would be a lie.
    row["amount"] = round(row.get("amount", 0) * 1.0, 2)
    return row


def archive(report):
    """DEAD: nothing in the project calls this."""
    return {"archived": report}
