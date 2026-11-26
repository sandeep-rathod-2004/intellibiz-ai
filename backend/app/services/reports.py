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


def _metric_availability(profile: dict, metric_name: str) -> tuple[str, str]:
    metrics = profile.get("financial_metrics")
    item = metrics.get(metric_name) if isinstance(metrics, dict) else None
    if not isinstance(item, dict):
        return "Unavailable (metric semantics not supplied)", ""
    status = item.get("status")
    if status == "ambiguous":
        candidates = item.get("candidates", [])
        return f"Unavailable (ambiguous: {', '.join(map(str, candidates))})", ""
    if status != "available":
        return "Unavailable", ""
    return "", str(item.get("column") or "")


def _business_metric_rows(profile: dict) -> list[list[str]]:
    kpis = profile.get("kpis") if isinstance(profile.get("kpis"), dict) else {}
    financial = profile.get("financial_metrics") if isinstance(profile.get("financial_metrics"), dict) else {}
    margin = financial.get("profit_margin") if isinstance(financial.get("profit_margin"), dict) else {}
    margin_label = (
        "Unweighted mean profit margin (%)"
        if margin.get("unit") == "percent"
        else "Unweighted mean profit margin (source units unspecified)"
    )
    definitions = [
        ("Total revenue", "revenue", "total_revenue", "total"),
        ("Total sales amount", "sales_amount", "total_sales_amount", "total"),
        ("Average sales amount", "sales_amount", "average_sales_amount", "average"),
        ("Total profit", "profit", "total_profit", "total"),
        ("Total expenses", "expenses", "total_expenses", "total"),
        ("Units sold", "units_sold", "total_units_sold", "total"),
        ("Average units per record", "units_sold", "average_units_sold", "average"),
        ("Transaction count", "transaction_count", "transaction_count", "count"),
        (margin_label, "profit_margin", "average_profit_margin", "average"),
    ]
    rows = [["Business metric", "Value", "Source column"]]
    for label, semantic_name, kpi_name, field in definitions:
        unavailable, source_column = _metric_availability(profile, semantic_name)
        if unavailable:
            value = unavailable
        else:
            raw_value = kpis.get(kpi_name)
            if field == "count" and isinstance(raw_value, int) and not isinstance(raw_value, bool):
                value = f"{raw_value:,}"
            else:
                value = _format_metric(raw_value)
            if value == "Unavailable":
                unavailable, source_column = _metric_availability(profile, semantic_name)
                value = unavailable or value
        rows.append([label, value, source_column])

    growth = kpis.get("growth")
    if isinstance(growth, dict):
        growth_value = _format_metric(growth.get("percent"))
        value = (
            f"{growth_value}% ({growth.get('previous_period')} to {growth.get('current_period')})"
            if growth_value != "Unavailable"
            else "Unavailable"
        )
        rows.append([f"Monthly growth: {growth.get('metric', 'financial metric')}", value, str(growth.get("metric", ""))])
    else:
        growth_status = kpis.get("growth_status")
        reason = growth_status.get("reason") if isinstance(growth_status, dict) else None
        rows.append(["Month-over-month growth", f"Unavailable ({reason})" if reason else "Unavailable", ""])
    return rows


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
        Paragraph("Business metrics", styles["Heading2"]),
        Paragraph(
            "Financial values are shown only when a source column has an unambiguous recognized meaning. "
            "Profit margins use an unweighted mean of source entries, never a sum or a revenue-weighted margin. "
            "Unavailable values are not inferred.",
            styles["BodyText"],
        ),
    ]

    business_table = Table(_business_metric_rows(profile), repeatRows=1)
    business_table.setStyle(
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
    story.extend([business_table, Spacer(1, 16), Paragraph("Numeric column statistics", styles["Heading2"])])
    story.append(
        Paragraph(
            "These are raw column sums and means, not normalized financial totals. "
            "A margin column sum is not total profit. Compare columns only when their units are compatible.",
            styles["BodyText"],
        )
    )

    data = [["Column", "Column sum", "Column mean", "Minimum", "Maximum"]]
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
