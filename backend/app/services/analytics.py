from io import BytesIO
import math
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


_FINANCIAL_ALIASES = {
    "revenue": {
        "revenue", "total_revenue", "gross_revenue", "net_revenue",
        "revenue_amount", "revenue_total", "turnover",
    },
    "sales_amount": {
        "sales_amount", "sale_amount", "sales_value", "sale_value",
        "total_sales", "total_sale", "gross_sales", "net_sales",
        "sales_revenue",
    },
    "profit": {
        "profit", "total_profit", "gross_profit", "net_profit",
        "profit_amount", "earnings", "total_earnings",
    },
    "profit_margin": {
        "profit_margin", "gross_profit_margin", "net_profit_margin",
        "profit_margin_pct", "profit_margin_percent", "profit_pct",
        "profit_percentage", "gross_profit_margin_pct", "net_profit_margin_pct",
    },
    "expenses": {
        "expense", "expenses", "total_expense", "total_expenses",
        "operating_expense", "operating_expenses", "expense_amount",
        "expenses_amount",
    },
    "units_sold": {
        "unit", "units", "quantity", "qty", "units_sold",
        "quantity_sold", "qty_sold", "sales_quantity", "sales_qty",
        "items_sold",
    },
}
_AMBIGUOUS_SALES_NAMES = {"sale", "sales"}
_TRANSACTION_ID_NAMES = {
    "transaction_id", "transaction_number", "order_id", "order_number",
    "invoice_id", "invoice_number", "receipt_id", "receipt_number",
}
_PROFIT_MARGIN_PERCENT_NAMES = {
    "profit_margin_pct", "profit_margin_percent", "profit_pct",
    "profit_percentage", "gross_profit_margin_pct", "net_profit_margin_pct",
}
_CURRENCY_SUFFIXES = {"usd", "eur", "gbp", "inr", "cad", "aud"}


def _canonical_metric_name(column: object) -> str:
    name = _normalized_name(column)
    parts = name.split("_")
    while len(parts) > 1 and parts[-1] in _CURRENCY_SUFFIXES:
        parts.pop()
    return "_".join(parts)


def _resolve_financial_column(columns: list[object], metric: str) -> dict[str, object]:
    aliases = _FINANCIAL_ALIASES[metric]
    strong_candidates = [
        column for column in columns
        if _canonical_metric_name(column) in aliases
    ]
    unqualified = []
    if metric == "sales_amount":
        unqualified = [
            column for column in columns
            if _normalized_name(column) in _AMBIGUOUS_SALES_NAMES
        ]
    strong_candidates = list(dict.fromkeys(strong_candidates))
    if len(strong_candidates) > 1:
        return {"status": "ambiguous", "column": None, "candidates": [str(item) for item in strong_candidates]}
    if strong_candidates:
        return {
            "status": "available",
            "column": strong_candidates[0],
            "candidates": [str(strong_candidates[0])],
        }
    if unqualified:
        return {
            "status": "ambiguous",
            "column": None,
            "candidates": [str(item) for item in unqualified],
            "reason": "unqualified_sales_name",
        }
    if not strong_candidates:
        return {"status": "unavailable", "column": None, "candidates": []}
    return {"status": "unavailable", "column": None, "candidates": []}


def _resolve_transaction_id(columns: list[object]) -> dict[str, object]:
    candidates = [column for column in columns if _canonical_metric_name(column) in _TRANSACTION_ID_NAMES]
    if len(candidates) > 1:
        return {"status": "ambiguous", "column": None, "candidates": [str(item) for item in candidates]}
    if not candidates:
        return {"status": "unavailable", "column": None, "candidates": []}
    return {"status": "available", "column": candidates[0], "candidates": [str(candidates[0])]}


def _financial_metrics(df: pd.DataFrame) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for name in _FINANCIAL_ALIASES:
        resolved = _resolve_financial_column(list(df.columns), name)
        source_column = resolved["column"]
        item: dict[str, object] = {
            **resolved,
            "column": str(source_column) if source_column is not None else None,
            "valid_count": 0,
            "total": None,
            "average": None,
        }
        if resolved["status"] == "available":
            column = source_column
            if name == "profit_margin":
                values = _numeric_values(df[column])
                average = _finite_mean(values)
                item.update({
                    "valid_count": int(len(values)),
                    "average": _rounded_finite(average, 4),
                    "unit": "percent" if _canonical_metric_name(column) in _PROFIT_MARGIN_PERCENT_NAMES else "source_units_unspecified",
                    "aggregation": "unweighted_mean_only",
                })
                if len(values) and average is None:
                    item.update({"status": "unavailable", "reason": "aggregation_overflow"})
            else:
                values = _numeric_values(df[column])
                total = _finite_sum(values)
                average = _finite_mean(values)
                item.update({
                    "valid_count": int(len(values)),
                    "total": _rounded_finite(total),
                    "average": _rounded_finite(average),
                    "aggregation": "sum_and_mean",
                })
            if not len(values):
                item["status"] = "unavailable"
                item["reason"] = "no_valid_numeric_values"
            elif name != "profit_margin" and (total is None or average is None):
                item.update({"status": "unavailable", "reason": "aggregation_overflow"})
        elif resolved["status"] == "ambiguous":
            item["reason"] = "multiple_or_unqualified_columns"
        else:
            item["reason"] = "no_recognized_column"
        result[name] = item

    transaction = _resolve_transaction_id(list(df.columns))
    transaction_column = transaction["column"]
    transaction_item: dict[str, object] = {
        **transaction,
        "column": str(transaction_column) if transaction_column is not None else None,
        "count": None,
        "aggregation": "distinct_non_null_identifiers",
    }
    if transaction["status"] == "available":
        column = transaction_column
        identifiers = [value for value in df[column] if _is_valid_identifier(value)]
        distinct = {_identifier_key(value) for value in identifiers}
        count = len(distinct)
        transaction_item.update({"count": count, "valid_count": len(identifiers)})
        if count == 0:
            transaction_item.update({"status": "unavailable", "reason": "no_valid_identifiers"})
    elif transaction["status"] == "ambiguous":
        transaction_item["reason"] = "multiple_transaction_identifier_columns"
    else:
        transaction_item["reason"] = "no_recognized_transaction_identifier"
    result["transaction_count"] = transaction_item
    return result


def _numeric_values(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    return values[np.isfinite(values)]


def _finite_sum(values: pd.Series) -> float | None:
    try:
        total = math.fsum(float(value) for value in values)
    except (OverflowError, ValueError):
        return None
    return total if math.isfinite(total) else None


def _finite_mean(values: pd.Series) -> float | None:
    if values.empty:
        return None
    numbers = [float(value) for value in values]
    scale = max(abs(value) for value in numbers)
    if scale == 0:
        return 0.0
    try:
        mean = math.fsum(value / scale for value in numbers) / len(numbers) * scale
    except (OverflowError, ValueError):
        return None
    return mean if math.isfinite(mean) else None


def _rounded_finite(value: float | None, digits: int = 2) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    try:
        rounded = round(value, digits)
    except (OverflowError, ValueError):
        return None
    return rounded if math.isfinite(rounded) else None


def _is_valid_identifier(value: object) -> bool:
    missing = pd.isna(value)
    if isinstance(missing, (bool, np.bool_)) and bool(missing):
        return False
    try:
        hash(value)
    except TypeError:
        return False
    # Whitespace-only IDs are blank, but nonblank strings are kept verbatim.
    # Thus " A " remains distinct from "A" to avoid silently merging IDs.
    return not (isinstance(value, str) and not value.strip())


def _identifier_key(value: object) -> tuple[str, object]:
    if isinstance(value, np.generic):
        value = value.item()
    return (f"{type(value).__module__}.{type(value).__qualname__}", value)


def _finite_json(value: object) -> object:
    """Replace non-finite numbers anywhere in the API profile with null."""
    if isinstance(value, dict):
        return {key: _finite_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite_json(item) for item in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


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
        return None, {"status": "unavailable", "reason": "date_or_financial_metric_unavailable"}
    dates = pd.to_datetime(df[date_col], errors="coerce", utc=True)
    values = _numeric_values(df[metric_col])
    observations = pd.DataFrame({"date": dates, "value": values}).dropna()
    if observations.empty:
        return None, {"status": "unavailable", "reason": "no_valid_dated_values"}
    observations["period"] = observations["date"].dt.tz_localize(None).dt.to_period("M").astype(str)
    monthly_values = {
        period: _finite_sum(group["value"])
        for period, group in observations.groupby("period", sort=True)
    }
    if any(value is None for value in monthly_values.values()):
        return None, {"status": "unavailable", "reason": "monthly_aggregation_overflow"}
    periods = pd.Series(monthly_values, dtype="float64")
    if len(periods) < 2:
        return None, {"status": "unavailable", "reason": "insufficient_months"}
    current_period = pd.Period(periods.index[-1], freq="M")
    previous_period = current_period - 1
    if str(previous_period) not in periods.index:
        return None, {
            "status": "unavailable",
            "reason": "missing_previous_month",
            "current_period": str(current_period),
            "required_previous_period": str(previous_period),
        }
    previous = float(periods.loc[str(previous_period)])
    current = float(periods.loc[str(current_period)])
    if previous <= 0:
        reason = "zero_previous_value" if previous == 0 else "negative_previous_value"
        return None, {
            "status": "unavailable",
            "reason": reason,
            "previous_period": str(previous_period),
            "current_period": str(current_period),
        }
    try:
        percent = (current - previous) / previous * 100
    except (OverflowError, ZeroDivisionError):
        percent = math.inf
    rounded_percent = _rounded_finite(percent, 2)
    rounded_previous = _rounded_finite(previous)
    rounded_current = _rounded_finite(current)
    if rounded_percent is None or rounded_previous is None or rounded_current is None:
        return None, {
            "status": "unavailable",
            "reason": "growth_calculation_overflow",
            "previous_period": str(previous_period),
            "current_period": str(current_period),
        }
    return {
        "metric": str(metric_col),
        "percent": rounded_percent,
        "previous_period": str(previous_period),
        "current_period": str(current_period),
        "previous_value": rounded_previous,
        "current_value": rounded_current,
    }, {"status": "available", "reason": None}


def profile(df: pd.DataFrame, *, include_all_summaries: bool = False):
    numeric = df.select_dtypes(include="number")
    financial_metrics = _financial_metrics(df)
    numeric_columns = list(numeric.columns)
    for metric_name in _FINANCIAL_ALIASES:
        resolved = _resolve_financial_column(list(df.columns), metric_name)
        if resolved["status"] == "available" and resolved["column"] not in numeric_columns:
            numeric_columns.append(resolved["column"])
    metrics = []
    numeric_columns = numeric_columns if include_all_summaries else numeric_columns[:12]
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
        if column != date_column and column not in numeric_columns
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

    revenue = financial_metrics["revenue"]
    sales_amount = financial_metrics["sales_amount"]
    profit = financial_metrics["profit"]
    units_sold = financial_metrics["units_sold"]
    expenses = financial_metrics["expenses"]
    trend_metric_name = (
        "revenue"
        if revenue["status"] == "available" or revenue.get("reason") == "aggregation_overflow"
        else "sales_amount"
    )
    trend_metric = financial_metrics[trend_metric_name]
    trend_column = (
        _resolve_financial_column(list(df.columns), trend_metric_name)["column"]
        if trend_metric["status"] == "available"
        or trend_metric.get("reason") == "aggregation_overflow" else None
    )
    growth, growth_status = _growth(df, date_column, trend_column)

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
                    "metric_type": trend_metric_name,
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
        "total_revenue": revenue["total"] if revenue["status"] == "available" else None,
        "total_profit": profit["total"] if profit["status"] == "available" else None,
        # Keep the legacy key, but only populate it when a monetary sales field is explicit.
        "average_sales": sales_amount["average"] if sales_amount["status"] == "available" else None,
        "total_sales_amount": sales_amount["total"] if sales_amount["status"] == "available" else None,
        "average_sales_amount": sales_amount["average"] if sales_amount["status"] == "available" else None,
        "total_units_sold": units_sold["total"] if units_sold["status"] == "available" else None,
        "average_units_sold": units_sold["average"] if units_sold["status"] == "available" else None,
        "total_expenses": expenses["total"] if expenses["status"] == "available" else None,
        "transaction_count": financial_metrics["transaction_count"]["count"]
        if financial_metrics["transaction_count"]["status"] == "available" else None,
        "average_profit_margin": financial_metrics["profit_margin"]["average"]
        if financial_metrics["profit_margin"]["status"] == "available" else None,
        "growth": growth,
        "growth_status": growth_status,
    }
    return _finite_json({
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
        "financial_metrics": financial_metrics,
        "kpis": kpis,
        "preview": [
            {str(key): _safe(value) for key, value in row.items()}
            for row in df.head(8).to_dict(orient="records")
        ],
    })


def insights(df: pd.DataFrame, data_profile: dict | None = None):
    data_profile = data_profile or profile(df)
    numeric_metrics = data_profile.get("numeric_summary", [])
    numeric_metrics = numeric_metrics if isinstance(numeric_metrics, list) else []
    items = []
    if not numeric_metrics:
        items.append("No numeric columns were detected. Add measurable fields to unlock KPI analysis.")

    financial_metrics = data_profile.get("financial_metrics", {})
    financial_columns = {
        str(column)
        for metric in financial_metrics.values()
        if isinstance(metric, dict)
        for column in metric.get("candidates", [])
    } if isinstance(financial_metrics, dict) else set()
    for metric in numeric_metrics[:8]:
        if not isinstance(metric, dict) or not metric.get("valid_count"):
            continue
        if str(metric.get("name", "")) in financial_columns:
            continue
        mean = _insight_number(metric.get("mean"))
        minimum = _insight_number(metric.get("min"))
        maximum = _insight_number(metric.get("max"))
        if mean is None or minimum is None or maximum is None:
            items.append({
                "title": f"{metric.get('name', 'Numeric column')}: summary unavailable",
                "detail": "One or more summary values could not be calculated safely for this column.",
                "type": "metric_availability",
            })
            continue
        items.append(
            {
                "title": f"{metric['name']}: average {mean:,.2f}",
                "detail": (
                    f"Observed range {minimum:,.2f} to {maximum:,.2f} "
                    f"across {metric['valid_count']} valid records."
                ),
                "type": "metric",
            }
        )

    if isinstance(financial_metrics, dict):
        for metric_name, metric in financial_metrics.items():
            if not isinstance(metric, dict) or metric.get("status") != "ambiguous":
                continue
            candidates = ", ".join(str(item) for item in metric.get("candidates", []))
            items.append({
                "title": f"{metric_name.replace('_', ' ').title()} metric is ambiguous",
                "detail": f"Multiple or unqualified columns match: {candidates}. No business KPI was calculated.",
                "type": "metric_availability",
            })
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


def _insight_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    return number if math.isfinite(number) else None
