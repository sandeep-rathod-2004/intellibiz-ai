from io import BytesIO
import re
from pathlib import Path
import zipfile

import numpy as np
import pandas as pd
from openpyxl.utils.exceptions import InvalidFileException

from app.core.config import settings
from app.ml.engine import _safe


class DatasetReadError(ValueError):
    pass


def _validate_xlsx_archive(source: str | Path | BytesIO) -> None:
    try:
        with zipfile.ZipFile(source) as archive:
            entries = archive.infolist()
            if len(entries) > 10000:
                raise DatasetReadError("Excel file contains too many internal components.")
            expanded_size = sum(entry.file_size for entry in entries)
            maximum_size = settings.max_xlsx_uncompressed_mb * 1024 * 1024
            if expanded_size > maximum_size:
                raise DatasetReadError(
                    f"Excel file expands beyond the {settings.max_xlsx_uncompressed_mb} MB limit."
                )
    except zipfile.BadZipFile:
        raise DatasetReadError("The Excel file is not a valid XLSX archive.") from None
    finally:
        if hasattr(source, "seek"):
            source.seek(0)


def read_dataset(source: str | Path | BytesIO, file_extension: str | None = None) -> pd.DataFrame:
    extension = (file_extension or str(source)).lower()
    if extension.endswith(".xlsx"):
        _validate_xlsx_archive(source)
        try:
            return pd.read_excel(source)
        except (InvalidFileException, OSError, ValueError, zipfile.BadZipFile):
            raise DatasetReadError("The Excel file could not be parsed.") from None
    try:
        return pd.read_csv(source)
    except (
        pd.errors.EmptyDataError,
        pd.errors.ParserError,
        OSError,
        UnicodeError,
        ValueError,
    ):
        raise DatasetReadError("The CSV file could not be parsed.") from None


def _normalized_name(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _find_named_column(columns: list[object], patterns: tuple[str, ...]) -> object | None:
    normalized = {column: _normalized_name(column) for column in columns}
    for pattern in patterns:
        exact = next((column for column, name in normalized.items() if name == pattern), None)
        if exact is not None:
            return exact
    for pattern in patterns:
        match = next((column for column, name in normalized.items() if pattern in name), None)
        if match is not None:
            return match
    return None


def _numeric_values(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    return values[np.isfinite(values)]


def _date_column(df: pd.DataFrame) -> object | None:
    named = _find_named_column(list(df.columns), ("date", "datetime", "timestamp", "time"))
    candidates = ([named] if named is not None else []) + [
        column for column in df.columns if column != named
    ]
    for column in candidates:
        if pd.api.types.is_numeric_dtype(df[column]):
            continue
        parsed = pd.to_datetime(df[column], errors="coerce", utc=True)
        if parsed.notna().mean() >= 0.8 and parsed.nunique() >= 2:
            return column
    return None


def _growth(df: pd.DataFrame, date_col: object | None, metric_col: object | None):
    if date_col is None or metric_col is None:
        return None
    dates = pd.to_datetime(df[date_col], errors="coerce", utc=True)
    values = _numeric_values(df[metric_col])
    observations = pd.DataFrame({"date": dates, "value": values}).dropna()
    if observations.empty:
        return None
    observations["period"] = observations["date"].dt.tz_localize(None).dt.to_period("M").astype(str)
    periods = observations.groupby("period", sort=True)["value"].sum()
    if len(periods) < 2:
        return None
    previous_period, current_period = periods.index[-2], periods.index[-1]
    previous, current = float(periods.iloc[-2]), float(periods.iloc[-1])
    if previous == 0:
        return None
    return {
        "metric": str(metric_col),
        "percent": round((current - previous) / abs(previous) * 100, 2),
        "previous_period": str(previous_period),
        "current_period": str(current_period),
        "previous_value": round(previous, 2),
        "current_value": round(current, 2),
    }


def profile(df: pd.DataFrame, *, include_all_summaries: bool = False):
    numeric = df.select_dtypes(include="number")
    metrics = []
    numeric_columns = numeric.columns if include_all_summaries else numeric.columns[:12]
    for column in numeric_columns:
        values = _numeric_values(df[column])
        metrics.append(
            {
                "name": str(column),
                "sum": round(float(values.sum()), 2) if len(values) else None,
                "mean": round(float(values.mean()), 2) if len(values) else None,
                "min": round(float(values.min()), 2) if len(values) else None,
                "max": round(float(values.max()), 2) if len(values) else None,
                "median": round(float(values.median()), 2) if len(values) else None,
                "std": round(float(values.std()), 2) if len(values) > 1 else None,
                "valid_count": int(len(values)),
                "q25": round(float(values.quantile(0.25)), 2) if len(values) else None,
                "q75": round(float(values.quantile(0.75)), 2) if len(values) else None,
            }
        )

    quality = [
        {
            "column": str(column),
            "missing": int(df[column].isna().sum()),
            "missing_pct": round(float(df[column].isna().mean() * 100), 2),
            "unique": int(df[column].nunique()),
            "dtype": str(df[column].dtype),
        }
        for column in df.columns
    ]
    date_column = _date_column(df)
    categories = []
    category_columns = [
        column
        for column in df.select_dtypes(exclude="number").columns
        if column != date_column
    ]
    selected_category_columns = category_columns if include_all_summaries else category_columns[:5]
    for column in selected_category_columns:
        counts = df[column].fillna("(missing)").astype(str).value_counts().head(8)
        categories.append(
            {
                "column": str(column),
                "values": [{"name": str(name), "count": int(count)} for name, count in counts.items()],
            }
        )

    revenue_column = _find_named_column(list(numeric.columns), ("revenue", "turnover"))
    profit_column = _find_named_column(list(numeric.columns), ("profit", "earnings"))
    sales_column = _find_named_column(list(numeric.columns), ("sales", "sale"))
    trend_column = revenue_column or sales_column
    revenue_values = _numeric_values(df[revenue_column]) if revenue_column is not None else pd.Series(dtype=float)
    profit_values = _numeric_values(df[profit_column]) if profit_column is not None else pd.Series(dtype=float)
    sales_values = _numeric_values(df[sales_column]) if sales_column is not None else pd.Series(dtype=float)

    category_analysis = []
    if trend_column is not None:
        for column in category_columns[:5]:
            if df[column].nunique(dropna=False) > 1000:
                continue
            grouped = (
                df.assign(_metric=_numeric_values(df[trend_column]))
                .groupby(df[column].fillna("(missing)").astype(str), dropna=False)["_metric"]
                .sum()
                .sort_values(ascending=False)
                .head(8)
            )
            category_analysis.append(
                {
                    "column": str(column),
                    "metric": str(trend_column),
                    "values": [
                        {"name": str(name), "sum": round(float(value), 2)}
                        for name, value in grouped.items()
                    ],
                }
            )

    correlations = []
    correlation_frame = numeric.iloc[:, :12].replace([np.inf, -np.inf], np.nan)
    if correlation_frame.shape[1] > 1:
        correlation_matrix = correlation_frame.corr(min_periods=3)
        pairs = []
        for left_index, left in enumerate(correlation_matrix.columns):
            for right in correlation_matrix.columns[left_index + 1:]:
                value = correlation_matrix.loc[left, right]
                if pd.notna(value):
                    pairs.append((abs(float(value)), str(left), str(right), float(value)))
        pairs.sort(reverse=True)
        correlations = [
            {"left": left, "right": right, "coefficient": round(value, 4), "absolute": round(magnitude, 4)}
            for magnitude, left, right, value in pairs[:10]
        ]

    kpis = {
        "total_revenue": round(float(revenue_values.sum()), 2) if len(revenue_values) else None,
        "total_profit": round(float(profit_values.sum()), 2) if len(profit_values) else None,
        "average_sales": round(float(sales_values.mean()), 2) if len(sales_values) else None,
        "growth": _growth(df, date_column, trend_column),
    }
    return {
        "rows": int(len(df)),
        "columns": int(len(df.columns)),
        "column_names": [str(column) for column in df.columns],
        "date_column": str(date_column) if date_column is not None else None,
        "numeric_summary": metrics,
        "quality": quality,
        "duplicate_rows": int(df.duplicated().sum()),
        "categories": categories,
        "category_analysis": category_analysis,
        "correlations": correlations,
        "kpis": kpis,
        "preview": [
            {str(key): _safe(value) for key, value in row.items()}
            for row in df.head(8).to_dict(orient="records")
        ],
    }


def insights(df: pd.DataFrame, data_profile: dict | None = None):
    numeric = df.select_dtypes(include="number")
    items = []
    if numeric.empty:
        return ["No numeric columns were detected. Add measurable fields to unlock KPI analysis."]

    for column in numeric.columns[:8]:
        values = _numeric_values(df[column])
        if len(values):
            items.append(
                {
                    "title": f"{column}: average {values.mean():,.2f}",
                    "detail": (
                        f"Observed range {values.min():,.2f} to {values.max():,.2f} "
                        f"across {len(values)} valid records."
                    ),
                    "type": "metric",
                }
            )

    data_profile = data_profile or profile(df)
    if data_profile["duplicate_rows"]:
        items.append(
            {
                "title": "Duplicate records detected",
                "detail": f"{data_profile['duplicate_rows']} exact duplicate rows are present.",
                "type": "quality",
            }
        )
    growth = data_profile["kpis"]["growth"]
    if growth:
        items.append(
            {
                "title": f"{growth['metric']}: {growth['percent']:+.2f}% month over month",
                "detail": (
                    f"Computed from {growth['previous_period']} ({growth['previous_value']:,.2f}) "
                    f"to {growth['current_period']} ({growth['current_value']:,.2f})."
                ),
                "type": "trend",
            }
        )
    if data_profile["correlations"]:
        strongest = data_profile["correlations"][0]
        items.append(
            {
                "title": "Strongest numeric relationship",
                "detail": (
                    f"{strongest['left']} and {strongest['right']} have correlation "
                    f"{strongest['coefficient']:.2f}. Correlation does not establish causation."
                ),
                "type": "relationship",
            }
        )
    return items
