import pandas as pd

from app.services.analytics import profile
from app.services.reports import _business_metric_rows, build_report


def test_report_escapes_user_controlled_text_and_handles_unavailable_metrics():
    report = build_report(
        "<img src='/private-file'> & Dataset",
        {
            "rows": 2,
            "columns": 1,
            "numeric_summary": [
                {
                    "name": "<Revenue & Profit>",
                    "sum": None,
                    "mean": None,
                    "min": None,
                    "max": None,
                }
            ],
        },
        [
            {
                "title": "<img src='/private-file'>",
                "detail": "Revenue & profit",
            },
            "A textual observation",
        ],
    )

    assert report.read(5) == b"%PDF-"


def test_report_business_rows_use_semantic_metrics_and_report_ambiguity():
    frame = pd.DataFrame(
        {
            "profit": [10, 20],
            "profit_margin_pct": [10, 20],
            "revenue": [100, 200],
            "net_revenue": [90, 180],
        }
    )
    result = profile(frame)
    rows = _business_metric_rows(result)
    by_label = {row[0]: row[1:] for row in rows[1:]}

    # Independent arithmetic: profit=30; percentage margin mean=15; two
    # revenue candidates mean no single revenue total may be selected.
    assert by_label["Total profit"] == ["30.00", "profit"]
    assert by_label["Unweighted mean profit margin (%)"] == ["15.00", "profit_margin_pct"]
    assert "ambiguous: revenue, net_revenue" in by_label["Total revenue"][0]
