"""Генератор детерминированного demo-датасета и загрузчик конкурсного CSV (§28).

Demo-генератор воспроизводит ключевую структуру реальной задачи:
сезонная кривая NDVI + погодная модуляция + шум + пропуски. Используется
провайдером demo-fallback, тестами и обучением без конкурсного файла.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

from ml.data.contract import TARGET_COL, normalize_columns


def _polygon_seed(polygon_id: str, seed: int) -> int:
    h = int(hashlib.sha256(f"{polygon_id}:{seed}".encode()).hexdigest(), 16)
    return (h + seed * 7919) % (2**31 - 1)


def generate_polygon_series(
    polygon_id: str,
    start: str = "2019-01-01",
    end: str = "2024-12-31",
    freq: str = "7D",
    seed: int = 42,
) -> pd.DataFrame:
    """Сезонный вегетационный цикл с погодной модуляцией (юг РФ)."""
    rng = np.random.default_rng(_polygon_seed(polygon_id, seed))
    dates = pd.date_range(start=start, end=end, freq=freq)
    n = len(dates)
    doy = dates.dayofyear.to_numpy()

    # Фенология: базовый уровень + яровой пик + озимый второй пик поменьше.
    base = 0.28 + 0.42 * np.exp(-0.5 * ((doy - 165) / 55) ** 2)
    base += 0.10 * np.exp(-0.5 * ((doy - 280) / 40) ** 2)
    # Межгодовой дрейф и индивидуальность поля.
    year_drift = (dates.year.to_numpy() - 2019) * 0.004
    field_shift = (rng.random() - 0.5) * 0.08
    # Погодная модуляция: жара/засуха просаживают NDVI с лагом.
    temp = 12 + 14 * np.sin(2 * np.pi * (doy - 100) / 365) + rng.normal(0, 2.5, n)
    rain = np.clip(rng.exponential(4.0, n) * (0.4 + 0.6 * np.cos(2 * np.pi * (doy - 60) / 365) ** 2), 0, 60)
    soil = np.clip(0.35 - 0.006 * np.clip(temp - 20, 0, None) + 0.004 * rain + rng.normal(0, 0.02, n), 0.05, 0.6)
    stress = np.clip((temp - 28) / 10, 0, 1) * 0.12 + np.clip((0.22 - soil) / 0.2, 0, 1) * 0.15
    ndvi = np.clip(base + field_shift + year_drift - stress + rng.normal(0, 0.015, n), 0.05, 0.95)
    # Вставка 1-2 засушливых эпизодов — материал для нетривиальных аномалий (§18).
    for _ in range(rng.integers(1, 3)):
        s = rng.integers(0, max(n - 6, 1))
        ndvi[s : s + 4] -= rng.uniform(0.10, 0.22)

    evi = np.clip(ndvi * 0.82 + rng.normal(0, 0.012, n), 0.03, 0.9)
    ndwi = np.clip((soil - 0.3) * 1.5 + rng.normal(0, 0.02, n), -0.5, 0.6)
    cloud = np.clip(rng.beta(2, 12, n) + (rain > 12) * 0.25, 0, 1)
    quality = np.clip(1 - cloud * 0.9 - rng.random(n) * 0.05, 0.05, 1.0)
    radiation = np.clip(18 + 10 * np.sin(2 * np.pi * (doy - 100) / 365) + rng.normal(0, 1.5, n), 2, 32)
    humidity = np.clip(65 - (temp - 15) * 1.2 + rng.normal(0, 5, n), 15, 95)

    return pd.DataFrame(
        {
            "polygon_id": polygon_id,
            "date": dates.date,
            TARGET_COL: np.round(ndvi, 5),
            "evi": np.round(evi, 5),
            "ndwi": np.round(ndwi, 5),
            "temperature": np.round(temp, 2),
            "precipitation": np.round(rain, 2),
            "soil_moisture": np.round(soil, 4),
            "radiation": np.round(radiation, 2),
            "humidity": np.round(humidity, 1),
            "cloud_fraction": np.round(cloud, 3),
            "data_quality": np.round(quality, 3),
            "is_synthetic_gap": False,
            "provider": "demo",
            "processing_version": "v1",
        }
    )


def generate_demo_dataset(
    n_polygons: int = 8,
    start: str = "2019-01-01",
    end: str = "2024-12-31",
    freq: str = "7D",
    seed: int = 42,
) -> pd.DataFrame:
    frames = [
        generate_polygon_series(f"AOI-{i + 1:05d}", start=start, end=end, freq=freq, seed=seed)
        for i in range(n_polygons)
    ]
    out = pd.concat(frames, ignore_index=True).sort_values(["polygon_id", "date"]).reset_index(drop=True)
    return out


def load_train_dataset(path: str | Path | None = None) -> tuple[pd.DataFrame, str]:
    """Возвращает (df, источник). Если конкурсного CSV нет — demo-датасет."""
    candidates = [Path(path)] if path else []
    candidates += [Path("data/train_dataset.csv"), Path("train_dataset.csv")]
    for cand in candidates:
        if cand and cand.exists():
            df = normalize_columns(pd.read_csv(cand))
            return df, str(cand)
    return generate_demo_dataset(), "demo"
