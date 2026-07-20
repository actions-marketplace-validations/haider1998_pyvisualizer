"""Model training."""


def train_model(features, config):
    params = _hyperparams(config)
    return _fit(features, params)


def _hyperparams(config):
    return {"lr": config.get("lr", 0.01)}


def _fit(features, params):
    return {"model": "fitted", "params": params}
