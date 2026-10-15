"""A4 visit briefing with the TANAPA logo and the coat of arms."""

from __future__ import annotations

from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from services.common.settings import ROOT

FOREST = colors.HexColor("#10281c")
GOLD = colors.HexColor("#e3a008")
CREAM = colors.HexColor("#f7f2e8")
INK = colors.HexColor("#142019")
MUTED = colors.HexColor("#5d675f")

LOGO = ROOT / "apps" / "web" / "public" / "brand" / "logo.png"
ARMS = ROOT / "apps" / "web" / "public" / "brand" / "arms.png"

_SEASON = {"high": "High season", "low": "Low season", "all": "All year"}


def render_briefing_pdf(briefing: dict) -> bytes:
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=34 * mm,
        bottomMargin=18 * mm,
        title="SafariAI park visit briefing",
        author="SafariAI Tanzania",
    )
    styles = _styles()
    story = [Paragraph("Visit plan", styles["cover"]), Spacer(1, 2 * mm)]
    story.append(_receipt("Trip", _trip_rows(briefing), styles))
    if briefing.get("entry"):
        story.append(Spacer(1, 3 * mm))
        story.append(_receipt("Entry", briefing["entry"], styles))
    if briefing.get("plan"):
        story.append(Spacer(1, 3 * mm))
        story.append(_receipt("How to visit", briefing["plan"], styles))
    story.append(Spacer(1, 3 * mm))
    story.append(_receipt("Conservation fees", _fee_status_rows(briefing), styles))
    table = _fee_table(briefing, styles)
    if table:
        story.append(Spacer(1, 2 * mm))
        story.append(table)
    for estimate in briefing.get("estimates") or []:
        story.append(Spacer(1, 3 * mm))
        story.append(_receipt(f"Park entry estimate · {estimate['park_name']}", _estimate_rows(estimate), styles))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(
        "TANAPA · PO Box 3134, Arusha · +255 (0) 272 970 404 · info@tanzaniaparks.go.tz"
        " · Immigration · info@immigration.go.tz · +255 2850575",
        styles["note"],
    ))
    document.build(story, onFirstPage=_frame, onLaterPages=_frame)
    return buffer.getvalue()


def _styles():
    base = getSampleStyleSheet()
    base.add(ParagraphStyle(name="cover", fontName="Times-Bold", fontSize=16, leading=20, textColor=FOREST, alignment=TA_LEFT))
    base.add(ParagraphStyle(name="banner", fontName="Times-Bold", fontSize=11, leading=13, textColor=colors.white))
    base.add(ParagraphStyle(name="head", fontName="Times-Bold", fontSize=13, leading=16, textColor=FOREST, spaceBefore=8, spaceAfter=3))
    base.add(ParagraphStyle(name="body", fontName="Times-Roman", fontSize=10, leading=13, textColor=INK, spaceAfter=3))
    base.add(ParagraphStyle(name="note", fontName="Times-Italic", fontSize=9, leading=12, textColor=MUTED, spaceBefore=2))
    base.add(ParagraphStyle(name="cell", fontName="Times-Roman", fontSize=8, leading=10, textColor=INK))
    return base


def _frame(canvas, doc):
    canvas.saveState()
    width, height = A4
    canvas.setFillColor(FOREST)
    canvas.rect(0, height - 26 * mm, width, 26 * mm, fill=1, stroke=0)
    canvas.setFillColor(GOLD)
    canvas.rect(0, height - 27.4 * mm, width, 1.4 * mm, fill=1, stroke=0)
    if LOGO.exists():
        canvas.drawImage(str(LOGO), 14 * mm, height - 23 * mm, 16 * mm, 16 * mm, mask="auto", preserveAspectRatio=True)
    canvas.setFillColor(colors.white)
    canvas.setFont("Times-Bold", 13)
    canvas.drawString(34 * mm, height - 14 * mm, "SafariAI Tanzania")
    canvas.setFont("Times-Roman", 8)
    canvas.drawString(34 * mm, height - 19 * mm, "Park visit briefing  ·  official TANAPA fees and immigration rules")
    if ARMS.exists():
        canvas.drawImage(str(ARMS), width - 28 * mm, height - 23 * mm, 12 * mm, 16 * mm, mask="auto", preserveAspectRatio=True)
    canvas.setFillColor(FOREST)
    canvas.rect(0, 0, width, 10 * mm, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Times-Roman", 8)
    canvas.drawString(16 * mm, 4 * mm, "Confirm fees and visa rules on the official pages before you pay or travel.")
    canvas.restoreState()


def _receipt(title: str, rows: list[dict], styles) -> Table:
    data = [[Paragraph(_esc(title), styles["banner"]), ""]]
    for row in rows:
        data.append([
            Paragraph(_esc(str(row.get("label") or "")), styles["cell"]),
            Paragraph(_esc(str(row.get("value") or "")), styles["cell"]),
        ])
    table = Table(data, colWidths=[48 * mm, 130 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), FOREST),
        ("SPAN", (0, 0), (-1, 0)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 1), (0, -1), colors.HexColor("#efe6d4")),
        ("BACKGROUND", (1, 1), (1, -1), CREAM),
        ("FONTNAME", (0, 1), (0, -1), "Times-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e4d8c4")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return table


def _trip_rows(briefing: dict) -> list[dict]:
    origin = briefing.get("origin") or "Not written"
    location = briefing.get("location") or ""
    start = origin if location in {"", "unspecified"} else f"{origin} · {location}"
    rows = [
        {"label": "Date", "value": briefing.get("as_of") or ""},
        {"label": "Start", "value": start},
        {"label": "Days", "value": str(briefing["days"]) if briefing.get("days") else "Not written"},
        {"label": "Adults", "value": "Not written" if briefing.get("adults") is None else str(briefing.get("adults"))},
    ]
    for age in briefing.get("child_ages") or []:
        if age < 5:
            band = "Free, below 5"
        elif age <= 15:
            band = "5–15 row"
        else:
            band = "16 and above"
        rows.append({"label": f"Child age {age}", "value": band})
    parks = briefing.get("parks") or []
    if briefing.get("named_parks") is False:
        rows.append({"label": "Park list", "value": "Suggestion. No park was named."})
    if not parks:
        rows.append({"label": "Park", "value": "Not selected"})
    for park in parks:
        rows.append({"label": "Park", "value": park.get("name") or park.get("slug")})
        if park.get("area_km2"):
            rows.append({"label": "Area", "value": f"{park['area_km2']:,} km²"})
        if park.get("circuit"):
            rows.append({"label": "Circuit", "value": str(park["circuit"])})
        if park.get("established_year"):
            rows.append({"label": "Established", "value": str(park["established_year"])})
    return rows


def _fee_status_rows(briefing: dict) -> list[dict]:
    tariff = briefing.get("tariff") or {}
    if not tariff.get("rows"):
        return [{"label": "Status", "value": "No conservation-fee row for these parks"}]
    rows = [
        {"label": "Tariff", "value": tariff.get("title") or ""},
        {"label": "Valid", "value": f"{tariff.get('effective_from')} to {tariff.get('effective_until')}"},
        {"label": "Status", "value": f"In force on {briefing.get('as_of')}"},
        {"label": "Fee class", "value": f"{briefing.get('visitor', '')} — {briefing.get('visitor_reason', '')}"},
        {"label": "Currency", "value": "Official amounts in TZS; USD is approximate"},
        {"label": "Confirm", "value": tariff.get("source_url") or "https://www.tanzaniaparks.go.tz/tourism/visitor-information/tariff"},
    ]
    rows.extend({"label": "Note", "value": note} for note in tariff.get("notes") or [])
    return rows


def _estimate_rows(estimate: dict) -> list[dict]:
    rows = [
        {"label": line["label"], "value": f"{line['qty']} × {line['days']} days × TZS {_money(line['unit_tzs'])} = TZS {_money(line['total_tzs'])}"}
        for line in estimate["lines"]
    ]
    rows.append({"label": "Total", "value": f"TZS {_money(estimate['total_tzs'])} (≈ USD {_money(estimate['total_usd'] or 0)})"})
    rows.append({"label": "Not included", "value": "; ".join(estimate["excludes"])})
    return rows


def _fee_table(briefing: dict, styles):
    rows = (briefing.get("tariff") or {}).get("rows") or []
    if not rows:
        return None
    data = [["Park", "Fee", "Who", "Season", "TZS", "≈ USD"]]
    for row in rows:
        data.append([
            Paragraph(_esc(str(row.get("park_name", "")).replace(" National Park", "")), styles["cell"]),
            Paragraph(_esc(row["item"]), styles["cell"]),
            Paragraph(_esc(row["visitor_label"]), styles["cell"]),
            _SEASON.get(row["season"], row["season"]),
            _money(row["amount_tzs"]),
            _money(row["amount_usd"] or 0),
        ])
    table = Table(data, colWidths=[28 * mm, 52 * mm, 36 * mm, 22 * mm, 22 * mm, 18 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), FOREST),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Times-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Times-Roman"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 1), (-1, -1), CREAM),
        ("TEXTCOLOR", (0, 1), (-1, -1), INK),
        ("ALIGN", (4, 1), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e4d8c4")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return table


def _money(value: float) -> str:
    value = float(value or 0)
    if value >= 1000 or value == int(value):
        return f"{int(round(value)):,}"
    return f"{value:,.2f}"


def _esc(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
