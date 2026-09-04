"""Детерминированный smoke-тест pipeline без сети и без обученной модели."""
from __future__ import annotations

import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def main():
    from apps.api.engine import run_analysis

    res = run_analysis({"id": "AOI-00001"}, date(2023, 5, 1), date(2023, 9, 30))
    assert res["kpi"].get("current_ndvi") is not None, "KPI не посчитан"
    assert len(res["timeseries"]) > 0, "Пустой временной ряд"
    assert isinstance(res["anomalies"], list), "Аномалии не список"
    print(f"OK: KPI={res['kpi']} точек={len(res['timeseries'])} "
          f"аномалий={len(res['anomalies'])} источники={res['sources']}")
    if res["warnings"]:
        print("warnings:", *res["warnings"], sep="\n - ")


if __name__ == "__main__":
    main()
