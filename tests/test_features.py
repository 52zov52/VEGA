"""Тесты leakage-контроля и разбиений."""
import pandas as pd

from ml.data.dataset import generate_demo_dataset
from ml.evaluation.splits import leave_polygon_out, time_forward_splits
from ml.features.build import build_features, feature_columns
from ml.features.leakage import check_no_leakage


def test_no_leakage_on_demo():
    df = generate_demo_dataset(n_polygons=3, start="2022-01-01", end="2022-06-01", seed=1)
    feat, _ = build_features(df)
    cols = feature_columns(feat)
    assert check_no_leakage(feat, cols) == []


def test_time_splits_are_forward():
    df = generate_demo_dataset(n_polygons=2, start="2019-01-01", end="2024-12-31", seed=2)
    splits = time_forward_splits(df, n_splits=2)
    assert len(splits) >= 1
    for tr, va in splits:
        assert pd.to_datetime(df.loc[tr, "date"]).max() < pd.to_datetime(df.loc[va, "date"]).max()


def test_leave_polygon_out_disjoint():
    df = generate_demo_dataset(n_polygons=4, start="2023-01-01", end="2023-03-01", seed=3)
    for tr, va in leave_polygon_out(df, n_folds=2):
        assert set(df.loc[tr, "polygon_id"]).isdisjoint(set(df.loc[va, "polygon_id"]))
