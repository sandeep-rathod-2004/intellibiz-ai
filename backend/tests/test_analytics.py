from io import BytesIO
import json
import zipfile

import pandas as pd
import numpy as np
import pytest

from app.ml.engine import forecast_series
from app.core.config import settings
from app.services.analytics import DatasetReadError, insights, profile, read_dataset


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
    assert result["kpis"]["average_sales"] is None
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


def test_business_metrics_use_explicit_semantics_and_independent_expected_values():
    frame = pd.DataFrame(
        {
            "date": ["2025-01-01", "2025-01-15", "2025-02-01"],
            "transaction_id": ["A", "B", "B"],
            "revenue": [100, 200, 250],
            "sales_amount": [90, 210, 245],
            "units_sold": [2, 4, 5],
            "profit": [20, 40, 50],
            "profit_margin_pct": [20, 20, 20],
            "expenses": [10, 30, 35],
        }
    )

    result = profile(frame)

    # Hand-calculated: revenue=100+200+250; sales=90+210+245;
    # units=2+4+5; profit=20+40+50; expenses=10+30+35.
    assert result["kpis"]["total_revenue"] == 550
    assert result["kpis"]["total_sales_amount"] == 545
    assert result["kpis"]["average_sales_amount"] == 181.67
    assert result["kpis"]["average_sales"] == 181.67
    assert result["kpis"]["total_units_sold"] == 11
    assert result["kpis"]["average_units_sold"] == 3.67
    assert result["kpis"]["total_profit"] == 110
    assert result["kpis"]["total_expenses"] == 75
    assert result["kpis"]["transaction_count"] == 2
    assert result["kpis"]["average_profit_margin"] == 20
    assert result["financial_metrics"]["profit_margin"]["total"] is None
    assert result["kpis"]["growth"]["previous_value"] == 300
    assert result["kpis"]["growth"]["current_value"] == 250
    assert result["kpis"]["growth"]["percent"] == -16.67


def test_units_and_unqualified_sales_are_not_treated_as_money():
    result = profile(pd.DataFrame({"units": [3, 5], "sales": [3, 5]}))

    # Hand-calculated: units total 8 and mean 4; the plain "sales" label
    # does not establish whether these are dollars or quantities.
    assert result["kpis"]["total_units_sold"] == 8
    assert result["kpis"]["average_units_sold"] == 4
    assert result["kpis"]["total_sales_amount"] is None
    assert result["kpis"]["average_sales_amount"] is None
    assert result["kpis"]["average_sales"] is None
    assert result["financial_metrics"]["sales_amount"]["status"] == "ambiguous"
    generated_insights = insights(pd.DataFrame({"units": [3, 5], "sales": [3, 5]}), result)
    assert any("Sales Amount metric is ambiguous" == item["title"] for item in generated_insights)
    assert not any(str(item).startswith("sales: average") for item in generated_insights)


def test_profit_margin_is_classified_separately_and_never_summed_as_profit():
    result = profile(pd.DataFrame({"profit": [10, 20], "profit_margin": [0.1, 0.2]}))

    # Hand-calculated: profit total 30; mean margin 0.15 in source units.
    assert result["kpis"]["total_profit"] == 30
    assert result["kpis"]["average_profit_margin"] == 0.15
    assert result["financial_metrics"]["profit_margin"]["total"] is None
    assert result["financial_metrics"]["profit_margin"]["aggregation"] == "unweighted_mean_only"


def test_growth_requires_the_immediately_previous_calendar_month():
    result = profile(pd.DataFrame({"date": ["2025-01-01", "2025-03-01"], "revenue": [100, 200]}))

    # January to March is +100% over two months, not month-over-month growth.
    assert result["kpis"]["growth"] is None
    assert result["kpis"]["growth_status"]["reason"] == "missing_previous_month"
    assert result["kpis"]["growth_status"]["required_previous_period"] == "2025-02"


def test_growth_is_unavailable_when_previous_month_revenue_is_zero():
    result = profile(pd.DataFrame({"date": ["2025-01-01", "2025-02-01"], "revenue": [0, 20]}))

    # The denominator would be zero, so no finite growth percentage exists.
    assert result["kpis"]["growth"] is None
    assert result["kpis"]["growth_status"]["reason"] == "zero_previous_value"


def test_growth_is_unavailable_when_previous_month_revenue_is_negative():
    result = profile(pd.DataFrame({"date": ["2025-01-01", "2025-02-01"], "revenue": [-10, 20]}))

    # A negative prior net-revenue baseline does not define conventional
    # percentage growth, even though the raw difference is 30.
    assert result["kpis"]["growth"] is None
    assert result["kpis"]["growth_status"]["reason"] == "negative_previous_value"


def test_negative_null_infinite_and_invalid_financial_values_are_handled_safely():
    result = profile(pd.DataFrame({
        "revenue": pd.Series([10, -3, np.inf, None, "invalid"], dtype=object),
        "units_sold": pd.Series([2, -1, None, "invalid", 0], dtype=object),
        "profit": [0, -5, None, None, None],
        "expenses": [10, -2, np.inf, None, None],
    }))

    # Finite numeric revenue is 10 + (-3) = 7, units are 2 + (-1) + 0 = 1,
    # profit is 0 + (-5) = -5, expenses are 10 + (-2) = 8.
    assert result["kpis"]["total_revenue"] == 7
    assert result["kpis"]["total_units_sold"] == 1
    assert result["kpis"]["total_profit"] == -5
    assert result["kpis"]["total_expenses"] == 8
    assert result["kpis"]["transaction_count"] is None
    revenue_summary = next(item for item in result["numeric_summary"] if item["name"] == "revenue")
    assert revenue_summary["sum"] == 7
    assert revenue_summary["valid_count"] == 2


def test_multiple_revenue_candidates_are_explicitly_ambiguous():
    frame = pd.DataFrame({"revenue": [100, 200], "net_revenue": [90, 180]})
    result = profile(frame)

    # Neither candidate is privileged: summing either would invent a choice.
    assert result["kpis"]["total_revenue"] is None
    assert result["financial_metrics"]["revenue"]["status"] == "ambiguous"
    assert result["financial_metrics"]["revenue"]["candidates"] == ["revenue", "net_revenue"]
    assert any("Revenue metric is ambiguous" == item["title"] for item in insights(frame, result))


def test_unrecognized_numeric_fields_do_not_create_financial_kpis():
    result = profile(pd.DataFrame({"count": [2, 4], "score": [0.2, 0.8]}))

    # The numeric data has sums, but no recognized business semantics or IDs.
    for field in (
        "total_revenue", "total_profit", "average_sales", "total_sales_amount",
        "total_units_sold", "total_expenses", "transaction_count",
    ):
        assert result["kpis"][field] is None
    assert result["numeric_summary"][0]["sum"] == 6


def test_finite_helpers_calculate_totals_and_averages_without_overflow():
    result = profile(pd.DataFrame({
        "revenue": [1e308, -1e308, 12.0],
        "profit_margin_pct": [10.0, 20.0, 30.0],
    }))

    # Revenue total is 12 and mean is 4; margin mean is (10+20+30)/3 = 20.
    assert result["financial_metrics"]["revenue"]["total"] == 12
    assert result["financial_metrics"]["revenue"]["average"] == 4
    assert result["financial_metrics"]["profit_margin"]["average"] == 20
    json.dumps(result, allow_nan=False)


def test_financial_total_overflow_is_explicit_and_never_becomes_zero():
    result = profile(pd.DataFrame({"revenue": [1.7e308, 1.7e308]}))
    metric = result["financial_metrics"]["revenue"]

    # The finite mean is 1.7e308, but the mathematical sum exceeds float range.
    assert metric["status"] == "unavailable"
    assert metric["reason"] == "aggregation_overflow"
    assert metric["total"] is None
    assert metric["average"] == 1.7e308
    assert result["kpis"]["total_revenue"] is None
    json.dumps(result, allow_nan=False)


def test_overflowing_unrelated_numeric_summary_does_not_break_insights():
    frame = pd.DataFrame({"score": [1.7e308, 1.7e308]})

    result = profile(frame)
    generated = insights(frame, result)

    # Both inputs are finite; their mean and sum exceed the pandas aggregation
    # path's finite range, so the summary is unavailable rather than zero.
    score_summary = result["numeric_summary"][0]
    assert score_summary["valid_count"] == 2
    assert score_summary["sum"] is None
    assert score_summary["mean"] is None
    assert any(item.get("title") == "score: summary unavailable" for item in generated)
    json.dumps({"profile": result, "insights": generated}, allow_nan=False)


def test_profit_percentage_alias_has_explicit_percent_units():
    result = profile(pd.DataFrame({"profit_percentage": [12.0, 18.0]}))
    metric = result["financial_metrics"]["profit_margin"]

    # The source explicitly says percentage; mean is (12+18)/2 = 15 percent.
    assert metric["average"] == 15
    assert metric["unit"] == "percent"
    assert metric["aggregation"] == "unweighted_mean_only"


def test_profit_margin_without_unit_semantics_is_labeled_unknown():
    result = profile(pd.DataFrame({"profit_margin": [0.15, 0.25]}))
    metric = result["financial_metrics"]["profit_margin"]

    # Mean remains 0.20 in source units; no conversion to 20 percent is inferred.
    assert metric["average"] == 0.2
    assert metric["unit"] == "source_units_unspecified"


def test_transaction_count_filters_blank_identifiers_and_keeps_types_distinct():
    frame = pd.DataFrame({
        "transaction_id": pd.Series(["A", "A", None, "", "   ", 1, "1", 2], dtype=object)
    })
    result = profile(frame)

    # Valid identifiers are A, numeric 1, string "1", and numeric 2: four distinct IDs.
    assert result["kpis"]["transaction_count"] == 4
    assert result["financial_metrics"]["transaction_count"]["valid_count"] == 5


def test_transaction_ids_preserve_nonblank_surrounding_whitespace():
    result = profile(pd.DataFrame({"transaction_id": ["TX-1", " TX-1 ", "TX-1"]}))

    # Policy: only whitespace-only IDs are discarded. Nonblank strings are
    # preserved verbatim, so the padded ID remains distinct from TX-1.
    assert result["kpis"]["transaction_count"] == 2


def test_monthly_aggregation_overflow_makes_growth_unavailable():
    result = profile(pd.DataFrame({
        "date": ["2025-01-01", "2025-01-15", "2025-02-01"],
        "revenue": [1.7e308, 1.7e308, 10.0],
    }))

    # January's sum is outside finite float range; February growth is therefore unavailable.
    assert result["kpis"]["growth"] is None
    assert result["kpis"]["growth_status"]["reason"] == "monthly_aggregation_overflow"
    json.dumps(result, allow_nan=False)


def test_growth_percentage_overflow_is_unavailable():
    result = profile(pd.DataFrame({
        "date": ["2025-01-01", "2025-02-01"],
        "revenue": [1e-308, 1e308],
    }))

    # (1e308 - 1e-308) / 1e-308 * 100 exceeds finite float range.
    assert result["kpis"]["growth"] is None
    assert result["kpis"]["growth_status"]["reason"] == "growth_calculation_overflow"
    json.dumps(result, allow_nan=False)


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
