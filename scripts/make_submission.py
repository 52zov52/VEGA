"""Генерация конкурсного submission.csv (§29): anon_polygon_id,date,primary_ndvi_pred.

Использование:
    python scripts/make_submission.py --test data/test_features_1.csv --out submission.csv --models models

Тестовый CSV содержит строки с пропусками primary_ndvi (или без колонки) —
скрипт восстанавливает каждую скрытую точку контекстом прошлого одного
полигона и пишет строго валидный формат. Проверки — validate_submission.py.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ml.data.contract import TARGET_COL, normalize_columns  # noqa: E402
from ml.inference.predict import load_artifacts, predict_gaps  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", required=True)
    ap.add_argument("--out", default="submission.csv")
    ap.add_argument("--models", default="models")
    args = ap.parse_args()

    artifacts = load_artifacts(args.models)
    if artifacts is None:
        raise SystemExit("Модель не обучена: сначала python scripts/train.py")

    test = pd.read_csv(args.test)
    # конкурсный формат: anon_polygon_id,date — приводим к контракту
    test.columns = [c.strip() for c in test.columns]
    if "anon_polygon_id" in test.columns and "polygon_id" not in test.columns:
        test = test.rename(columns={"anon_polygon_id": "polygon_id"})
    test["polygon_id"] = test["polygon_id"].astype(str)
    test["date"] = pd.to_datetime(test["date"]).dt.date
    test = normalize_columns(test)
    # Скрытый тест: target отсутствует полностью или частично — это и восстанавливаем.
    if TARGET_COL not in test.columns:
        test[TARGET_COL] = float("nan")

    filled = predict_gaps(test, artifacts)
    sub = pd.DataFrame({
        "anon_polygon_id": test["polygon_id"],
        "date": pd.to_datetime(test["date"]).dt.strftime("%Y-%m-%d"),
        "primary_ndvi_true": filled.round(6),  # Платформа ожидает primary_ndvi_true
        "_gap": test["is_synthetic_gap"] if "is_synthetic_gap" in test.columns else True,
    })
    # Скоринговая выборка — строки с флагом скрытых точек; без флага — все строки.
    if "is_synthetic_gap" in test.columns:
        sub = sub[sub["_gap"] == True]  # noqa: E712 — флаг из CSV
    sub = sub.drop(columns=["_gap"]).drop_duplicates(["anon_polygon_id", "date"]).sort_values(
        ["anon_polygon_id", "date"])
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    sub.to_csv(args.out, index=False)
    print(f"submission: {len(sub)} rows -> {args.out}")


if __name__ == "__main__":
    main()
