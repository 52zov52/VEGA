"""Тесты leakage-контроля и разбиений (актуальный API: build_features -> (feat, cols))."""
import pandas as pd

from ml.data.dataset import generate_demo_dataset
from ml.evaluation.leakage import check_no_future_features, check_temporal_order
from ml.evaluation.splits import leave_polygon_out, time_forward_splits
from ml.features.build import build_features


def test_no_leakage_on_demo():
    df = generate_demo_dataset(n_polygons=3, start="2022-01-01", end="2022-06-01", seed=1)
    feat, cols = build_features(df)
    assert check_no_future_features(cols) == []


def test_time_splits_are_forward():
    df = generate_demo_dataset(n_polygons=2, start="2019-01-01", end="2024-12-31", seed=2)
    splits = time_forward_splits(df)
    assert len(splits) >= 1
    for tr, va in splits:
        assert check_temporal_order(tr, va) == []
        assert pd.to_datetime(tr["date"]).max() < pd.to_datetime(va["date"]).max()


def test_leave_polygon_out_disjoint():
    df = generate_demo_dataset(n_polygons=4, start="2023-01-01", end="2023-03-01", seed=3)
    seen = 0
    for tr, va, _pid in leave_polygon_out(df):
        assert set(tr["polygon_id"]).isdisjoint(set(va["polygon_id"]))
        seen += 1
    assert seen == 4
