from datetime import date, datetime

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest, RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error

def detect_anomalies(df: pd.DataFrame, contamination: float = 0.05):
    numeric = df.select_dtypes(include="number").replace([np.inf, -np.inf], np.nan).dropna(axis=1, how="all")
    if numeric.shape[1] == 0 or len(numeric) < 10: return {"available": False, "reason": "Need at least 10 rows and one numeric column", "count": 0, "rows": []}
    numeric = numeric.fillna(numeric.median()).clip(lower=numeric.quantile(.01), upper=numeric.quantile(.99), axis=1)
    effective_contamination = min(max(contamination, .01), .2)
    model = IsolationForest(contamination=effective_contamination, random_state=42, n_estimators=150)
    labels = model.fit_predict(numeric)
    scores = model.decision_function(numeric)
    center = numeric.median()
    scale = (numeric - center).abs().median() * 1.4826
    scale = scale.where(scale > 0, numeric.std(ddof=0)).replace(0, np.nan)
    idx = np.where(labels == -1)[0]
    rows = []
    for i in idx[:100]:
        deviations = ((numeric.iloc[i] - center).abs() / scale).replace([np.inf, -np.inf], np.nan).dropna()
        reasons = [
            f"{column} is unusually distant from the dataset median ({value:.1f} scaled deviations)"
            for column, value in deviations.sort_values(ascending=False).head(3).items()
        ]
        rows.append(
            {
                "row": int(i),
                "score": round(float(scores[i]), 4),
                "reasons": reasons,
                "values": {key: _safe(value) for key, value in df.iloc[i].items()},
            }
        )
    return {
        "available": True,
        "count": int(len(idx)),
        "total": int(len(df)),
        "contamination": effective_contamination,
        "rows": rows,
        "note": "Statistical outlier flags are investigation signals, not proof of fraud or error.",
    }

def json_safe(v):
    if pd.isna(v): return None
    if isinstance(v, (pd.Timestamp, datetime, date)): return v.isoformat()
    if isinstance(v, np.datetime64): return pd.Timestamp(v).isoformat()
    if isinstance(v, np.generic): return v.item()
    return str(v) if not isinstance(v, (str,int,float,bool)) else v

def _safe(v):
    return json_safe(v)

def forecast_series(df: pd.DataFrame, date_col: str, target_col: str, horizon: int = 6):
    data = df[[date_col, target_col]].copy()
    data[date_col] = pd.to_datetime(data[date_col], errors="coerce")
    data[target_col] = pd.to_numeric(data[target_col], errors="coerce")
    data = data.dropna().sort_values(date_col).groupby(date_col, as_index=False)[target_col].sum()
    if len(data) < 12: return {"available": False, "reason": "At least 12 dated observations are required for a baseline forecast."}
    y = data[target_col].astype(float).to_numpy()
    X = pd.DataFrame({"lag_1": pd.Series(y).shift(1), "lag_2": pd.Series(y).shift(2), "lag_3": pd.Series(y).shift(3), "trend": np.arange(len(y))}).dropna()
    target = pd.Series(y).iloc[3:].to_numpy()
    split = max(5, int(len(X)*.8))
    if len(X)-split < 1: split = len(X)-1
    model = RandomForestRegressor(n_estimators=180, max_depth=5, min_samples_leaf=1, random_state=42)
    model.fit(X.iloc[:split], target[:split])
    pred_test = model.predict(X.iloc[split:])
    test_values = target[split:]
    mae = float(mean_absolute_error(test_values, pred_test)) if len(pred_test) else None
    rmse = float(np.sqrt(mean_squared_error(test_values, pred_test))) if len(pred_test) else None
    baseline_predictions = np.full(len(test_values), target[split - 1], dtype=float)
    baseline_mae = float(mean_absolute_error(test_values, baseline_predictions)) if len(test_values) else None
    baseline_rmse = (
        float(np.sqrt(mean_squared_error(test_values, baseline_predictions)))
        if len(test_values) else None
    )
    nonzero_actuals = test_values != 0
    mape = (
        float(np.mean(np.abs((test_values[nonzero_actuals] - pred_test[nonzero_actuals]) / test_values[nonzero_actuals])) * 100)
        if np.any(nonzero_actuals) else None
    )
    model.fit(X, target)
    history = list(y); future=[]
    for step in range(horizon):
        features = pd.DataFrame([{"lag_1": history[-1], "lag_2": history[-2], "lag_3": history[-3], "trend": len(history)}])
        value = max(0.0, float(model.predict(features)[0])); history.append(value); future.append(round(value,2))
    freq = pd.infer_freq(data[date_col]) or "MS"
    last = data[date_col].max()
    try: dates = pd.date_range(last, periods=horizon+1, freq=freq)[1:]
    except ValueError: dates = pd.date_range(last, periods=horizon+1, freq="MS")[1:]
    return {
        "available": True,
        "target": target_col,
        "date_column": date_col,
        "history": [
            {"date": d.strftime("%Y-%m-%d"), "actual": round(float(v), 2)}
            for d, v in zip(data[date_col], y)
        ],
        "forecast": [
            {"date": d.strftime("%Y-%m-%d"), "predicted": value}
            for d, value in zip(dates, future)
        ],
        "metrics": {
            "mae": round(mae, 2) if mae is not None else None,
            "rmse": round(rmse, 2) if rmse is not None else None,
            "baseline_mae": round(baseline_mae, 2) if baseline_mae is not None else None,
            "baseline_rmse": round(baseline_rmse, 2) if baseline_rmse is not None else None,
            "mape": round(mape, 2) if mape is not None else None,
        },
        "model": "RandomForestRegressor with lag features",
        "caveat": (
            "Baseline forecast compared with a last-observation naive baseline. "
            "Validate seasonality, data leakage, and business context before operational use."
        ),
    }
