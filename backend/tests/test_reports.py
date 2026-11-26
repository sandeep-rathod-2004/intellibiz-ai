from app.services.reports import build_report


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
