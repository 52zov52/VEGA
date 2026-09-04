# Ablation study (GBM, synthetic gaps 1d/3d, valid 2024, RMSE)

Базовый self-supervised GBM (CatBoost): 1d 0.0731 / 3d 0.0668.

| Вариант | 1d | 3d | Вывод |
|---|---:|---:|---|
| Full (v20, 56 фичей) | 0.0731 | 0.0668 | — |
| − spatial_mean | 0.0729 | 0.0669 | нейтрально, оставлен |
| − weather (temp/precip rollings) | ≈ full | ≈ full | слабый сигнал на дневном шаге |
| − interp_now (plain GBM) | 0.0717* | 0.0715* | *другая шкала: без residual-формы; residual честнее |
| interp_now как признак без residual | = linear | = linear | вырождение в тождество — причина residual-формы |
| Seed-bagging ×5 | 0.0723 | — | нет эффекта (ошибка = bias/шум) |
| LightGBM / HGB вместо CatBoost | ±0.0003 | ±0.0003 | плато по алгоритму |

Стратификация ensemble (0.5/0/0.5) по days_since_obs, 1d:
dso 1–2: lin 0.0725 / gbm 0.0704 / ens 0.0649 (n=352);
dso 3–7: lin 0.0707 / gbm 0.0647 / ens 0.0621 (n=423);
dso 8–30: lin 0.0875 / gbm 0.0818 / ens 0.0826 (n=179);
dso 31+: ens 0.0882 лучший (gbm solo 0.1483 — спасает seasonal).
