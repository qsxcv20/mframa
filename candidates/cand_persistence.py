"""Baseline: persistence (predict last known value)."""


def predict(station, neighbors, target_time):
    s = station["series"]
    return s[-1][1] if s else None
