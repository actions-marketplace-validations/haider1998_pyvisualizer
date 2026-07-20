"""Local decorator shims with the same shape FastAPI's router methods have."""


def get(path):
    def wrap(fn):
        return fn

    return wrap


def post(path):
    def wrap(fn):
        return fn

    return wrap
