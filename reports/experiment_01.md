# Experiment 01 — baselines на synthetic gaps 7d
# Заполняется запуском: py scripts/train.py
# Ожидаемое: linear < nearest на коротких gaps, seasonal выигрывает на 14-30d, ensemble лучший везде.

# Experiment 02 — CatBoost vs LightGBM vs HistGB
# Сравнение бэкендов модели A при фиксированных признаках v1 и time-forward split.

# Experiment 03 — ensemble weights
# Grid search весов w1/w2/w3 на validation gaps; метрика RMSE + GapScore.
