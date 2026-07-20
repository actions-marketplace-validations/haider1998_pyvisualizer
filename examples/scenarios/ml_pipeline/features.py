"""Feature engineering."""


def build_features(rows):
    scaled = _scale(rows)
    return _encode(scaled)


def _scale(rows):
    return rows


def _encode(rows):
    return rows
