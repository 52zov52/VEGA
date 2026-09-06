"""Валидация submission.csv (§29). Код выхода 0 = файл принят, иначе ошибка.

Проверяет: колонки, формат даты, дубликаты polygon+date, пропуски, UTF-8,
разделитель запятая, диапазон NDVI.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "submission.csv")
    if not path.exists():
        print(f"FAIL: файл не найден: {path}")
        raise SystemExit(2)
    try:
        df = pd.read_csv(path, encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        print(f"FAIL: не читается как UTF-8 CSV: {e}")
        raise SystemExit(2)
    errors: list[str] = []
    if list(df.columns) != ["anon_polygon_id", "date", "primary_ndvi_true"]:
        errors.append(f"колонки должны быть anon_polygon_id,date,primary_ndvi_true, найдено: {list(df.columns)}")
    if df[["anon_polygon_id", "date"]].isna().any().any():
        errors.append("есть пустые anon_polygon_id/date")
    if df["primary_ndvi_true"].isna().any():
        errors.append("есть пропуски primary_ndvi_true")
    try:
        pd.to_datetime(df["date"], format="%Y-%m-%d")
    except Exception:  # noqa: BLE001
        errors.append("date не в формате YYYY-MM-DD")
    if df.duplicated(["anon_polygon_id", "date"]).any():
        errors.append("есть дубликаты polygon+date")
    vals = pd.to_numeric(df["primary_ndvi_true"], errors="coerce")
    if vals.isna().any() or ((vals < -0.2) | (vals > 1.2)).any():
        errors.append("primary_ndvi_pred вне разумного диапазона")
    if errors:
        print("FAIL:")
        for e in errors:
            print(f"  - {e}")
        raise SystemExit(1)
    print(f"OK: {len(df)} rows, {df['anon_polygon_id'].nunique()} polygons")


if __name__ == "__main__":
    main()
