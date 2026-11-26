from io import BytesIO
from math import isfinite
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def _format_metric(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        return "Unavailable"
    return f"{value:,.2f}"


def build_report(dataset_name: str, profile: dict, insight_items: list):
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=42,
        leftMargin=42,
        topMargin=42,
        bottomMargin=42,
    )
    styles = getSampleStyleSheet()
    rows = profile.get("rows", 0)
    columns = profile.get("columns", 0)
    story = [
        Paragraph("IntelliBiz AI | Executive Intelligence Brief", styles["Title"]),
        Paragraph(escape(str(dataset_name)), styles["Heading2"]),
        Paragraph(f"{rows:,} records · {columns} columns", styles["Normal"]),
        Spacer(1, 16),
        Paragraph("Key numeric indicators", styles["Heading2"]),
    ]

    data = [["Metric", "Total", "Average", "Minimum", "Maximum"]]
    for metric in profile.get("numeric_summary", [])[:10]:
        data.append(
            [
                str(metric.get("name", "Metric")),
                _format_metric(metric.get("sum")),
                _format_metric(metric.get("mean")),
                _format_metric(metric.get("min")),
                _format_metric(metric.get("max")),
            ]
        )

    table = Table(data, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#172554")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D7DEEA")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F6FB")]),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("PADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.extend(
        [
            table,
            Spacer(1, 18),
            Paragraph("Computed observations", styles["Heading2"]),
        ]
    )

    for item in insight_items[:12]:
        if isinstance(item, str):
            story.extend([Paragraph(escape(item), styles["BodyText"]), Spacer(1, 6)])
            continue
        if not isinstance(item, dict):
            continue
        title = escape(str(item.get("title", "Computed observation")))
        detail = escape(str(item.get("detail", "")))
        story.extend(
            [
                Paragraph(title, styles["Heading3"]),
                Paragraph(detail, styles["BodyText"]),
                Spacer(1, 6),
            ]
        )

    story.extend(
        [
            Spacer(1, 16),
            Paragraph(
                "Interpretation note: descriptive statistics and model outputs are "
                "decision-support signals, not causal conclusions or guarantees. "
                "Validate source data and business context.",
                styles["Italic"],
            ),
        ]
    )
    document.build(story)
    buffer.seek(0)
    return buffer
