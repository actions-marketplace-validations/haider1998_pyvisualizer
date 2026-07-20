"""The live training pipeline — everything real starts at run()."""

from evaluate import evaluate_model
from features import build_features
from ingest import load_dataset
from train import train_model


def run(config):
    raw = load_dataset(config["source"])
    features = build_features(raw)
    model = train_model(features, config)
    return evaluate_model(model, features)
