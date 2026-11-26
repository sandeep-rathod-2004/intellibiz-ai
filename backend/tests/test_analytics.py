from io import BytesIO
import zipfile

import pandas as pd
import pytest

from app.ml.engine import forecast_series
from app.core.config import settings
from app.services.analytics import DatasetReadError, profile, read_dataset


def test_profile_computes_named_kpis_growth_duplicates_and_category_totals():
    dataset = pd.DataFrame(
        [
            {"date": "2026-01-15", "region": "North", "sales": 2, "revenue": 100, "profit": 10},
            {"date": "2026-01-20", "region": "North", "sales": 3, "revenue": 50, "profit": 5},
            {"date": "2026-02-01", "region": "South", "sales": 4, "revenue": 200, "profit": 30},
            {"date": "2026-02-01", "region": "South", "sales": 4, "revenue": 200, "profit": 30},
        ]
    )

    result = profile(dataset)

    assert result["kpis"]["total_revenue"] == 550
    assert result["kpis"]["total_profit"] == 75
    assert result["kpis"]["average_sales"] == 3.25
    assert result["kpis"]["growth"]["percent"] == 166.67
    assert result["duplicate_rows"] == 1
    regional_totals = result["category_analysis"][0]["values"]
    assert regional_totals == [
        {"name": "South", "sum": 400.0},
        {"name": "North", "sum": 150.0},
    ]


def test_profile_does_not_infer_revenue_from_unrelated_numeric_fields():
    result = profile(pd.DataFrame({"count": [2, 4], "region": ["North", "South"]}))

    assert result["kpis"]["total_revenue"] is None
    assert result["kpis"]["total_profit"] is None
    assert result["kpis"]["average_sales"] is None
    assert result["kpis"]["growth"] is None


def test_forecast_reports_naive_baseline_and_only_valid_mape():
    dataset = pd.DataFrame(
        {
            "date": pd.date_range("2025-01-01", periods=18, freq="MS"),
            "revenue": [100 + 10 * index for index in range(18)],
        }
    )

    result = forecast_series(dataset, "date", "revenue", horizon=3)

    assert result["available"] is True
    assert result["metrics"]["mae"] is not None
    assert result["metrics"]["baseline_mae"] is not None
    assert result["metrics"]["baseline_rmse"] is not None
    assert result["metrics"]["mape"] is not None
    assert len(result["forecast"]) == 3


def test_forecast_reports_mape_as_unavailable_when_holdout_is_zero():
    dataset = pd.DataFrame(
        {
            "date": pd.date_range("2025-01-01", periods=18, freq="MS"),
            "revenue": [0 for _ in range(18)],
        }
    )

    result = forecast_series(dataset, "date", "revenue", horizon=1)

    assert result["available"] is True
    assert result["metrics"]["mape"] is None


def test_invalid_csv_errors_do_not_include_parser_input():
    with pytest.raises(DatasetReadError) as raised:
        read_dataset(BytesIO(b"private-marker,value\n\xff,1\n"), ".csv")

    assert str(raised.value) == "The CSV file could not be parsed."
    assert "private-marker" not in str(raised.value)


def test_xlsx_expansion_limit_rejects_archive_before_parsing(monkeypatch):
    monkeypatch.setattr(settings, "max_xlsx_uncompressed_mb", 1)
    source = BytesIO()
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", "x" * (1024 * 1024 + 1))
    source.seek(0)

    with pytest.raises(DatasetReadError, match="expands beyond"):
        read_dataset(source, ".xlsx")
