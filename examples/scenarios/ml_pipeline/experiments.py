"""Old experiments — the graveyard every ML repo grows. Nothing calls these."""


def train_model_v1_legacy(features):
    """DEAD: superseded by train.train_model months ago."""
    return _fit_legacy(features)


def _fit_legacy(features):
    """DEAD: only reachable from the dead legacy trainer."""
    return {"model": "old"}


def grid_search_abandoned(features):
    """DEAD: an abandoned experiment nothing ever wired in."""
    return [{"lr": lr} for lr in (0.1, 0.01)]
