"""
export/dashboard_pdf_export.py
Two separate, focused PDF reports meant for sharing outside the app
(top management, consultants) — kept as two files rather than one
combined document, since "the numbers" and "the list of items that may
have been forgotten" are usually shared with different people / for
different purposes:

- export_dashboard_summary_to_pdf: the stat cards, status pie chart, and
  estimated value by currency — no item-level list at all.
- export_stale_items_to_pdf: just the "Possibly Forgotten" item list, as
  its own document.

Both reuse the exact same visual house style already established in
pdf_export.py (title/section color, fonts, pie chart rendering) so a
report generated here looks like it belongs to the same family as the
existing per-project PDF report.
"""

import os
import tempfile
from datetime import datetime

import config as _config

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, PageBreak
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from xml.sax.saxutils import escape as _xml_escape

from export.pdf_export import (
    _pie_chart_from_counts, _setup_arabic_fonts, _shape_arabic, FONT_NAME,
)

TITLE_COLOR = colors.HexColor("#1F4E78")


def _e(value):
    return _xml_escape(_shape_arabic(str(value))) if value is not None else ""


def _styles():
    base = getSampleStyleSheet()
    title = ParagraphStyle("DashTitle", parent=base["Title"], fontName=FONT_NAME + "-Bold",
                            fontSize=20, textColor=TITLE_COLOR)
    subtitle = ParagraphStyle("DashSubtitle", parent=base["Normal"], alignment=TA_CENTER,
                               fontSize=10, textColor=colors.grey)
    section = ParagraphStyle("DashSection", parent=base["Heading2"], fontSize=13,
                              spaceBefore=14, spaceAfter=6, textColor=TITLE_COLOR)
    cell = ParagraphStyle("DashCell", parent=base["Normal"], fontSize=9, leading=11,
                           alignment=TA_LEFT, wordWrap="CJK")
    cell_right = ParagraphStyle("DashCellRight", parent=cell, alignment=TA_RIGHT)
    cell_center = ParagraphStyle("DashCellCenter", parent=cell, alignment=TA_CENTER)
    header_cell = ParagraphStyle("DashHeaderCell", parent=cell_center, textColor=colors.white,
                                  fontName=FONT_NAME + "-Bold", fontSize=9)
    # Use the Arabic-capable font for every paragraph when available.
    arabic_fonts = _setup_arabic_fonts()
    if arabic_fonts:
        regular, bold = arabic_fonts
        for st in (title, subtitle, section, cell, cell_right, cell_center, header_cell):
            st.fontName = bold if st.fontName.endswith("-Bold") else regular
    return {
        "title": title, "subtitle": subtitle, "section": section,
        "cell": cell, "cell_right": cell_right, "cell_center": cell_center,
        "header_cell": header_cell,
    }


def _footer(canvas_obj, doc):
    canvas_obj.saveState()
    canvas_obj.setFont(FONT_NAME, 8)
    canvas_obj.setFillColor(colors.grey)
    canvas_obj.drawRightString(doc.pagesize[0] - 1 * cm, 0.7 * cm, f"Page {doc.page}")
    canvas_obj.drawString(1 * cm, 0.7 * cm,
                           f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} \u2014 Project Tracker")
    logo = _config.logo_path()
    if logo:
        try:
            canvas_obj.drawImage(
                logo, doc.pagesize[0] - 4.1 * cm, doc.pagesize[1] - 2.7 * cm,
                width=3.1 * cm, height=2.0 * cm,
                preserveAspectRatio=True, mask="auto",
            )
        except Exception:
            pass
    canvas_obj.restoreState()


def export_dashboard_summary_to_pdf(db, project_ids, output_path, scope_label):
    """The stat cards + status breakdown + estimated value by currency —
    no item-level list. scope_label is shown as the report subtitle
    (e.g. a Group name, a single project's name, or "All Projects")."""
    summary = db.get_dashboard_summary(project_ids=project_ids)
    s = _styles()

    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        topMargin=2.8 * cm, bottomMargin=1.5 * cm, leftMargin=1.5 * cm, rightMargin=1.5 * cm,
    )
    story = []
    story.append(Paragraph("Project Dashboard Summary", s["title"]))
    story.append(Paragraph(
        f"{_e(scope_label)}  \u2014  Generated {datetime.now().strftime('%Y-%m-%d')}", s["subtitle"]
    ))
    story.append(Spacer(1, 0.6 * cm))

    # ---- Stat cards ----
    total_items = summary["item_count"]
    missing_cost = summary["missing_cost_count"]
    missing_pct = f"{missing_cost * 100 // total_items}%" if total_items else "0%"
    stale_count = len(summary["stale_items"])

    labels = ["Projects", "Total Items", "Missing Unit Cost", "Possibly Forgotten"]
    values = [str(summary["project_count"]), str(total_items),
              f"{missing_cost} ({missing_pct})", str(stale_count)]
    stat_table = Table(
        [[Paragraph(l, s["header_cell"]) for l in labels],
         [Paragraph(v, ParagraphStyle("StatVal", parent=s["cell_center"], fontSize=15,
                                       fontName=FONT_NAME + "-Bold")) for v in values]],
        colWidths=[4.25 * cm] * 4,
    )
    stat_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), TITLE_COLOR),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#C9CDD3")),
        ("BOX", (0, 0), (-1, -1), 0.75, TITLE_COLOR),
    ]))
    story.append(stat_table)

    # ---- Items by Status: pie chart + counts table, side by side ----
    story.append(Paragraph("Items by Status", s["section"]))
    status_counts = summary["status_counts"]
    chart_path = _pie_chart_from_counts(status_counts, title="")

    count_rows = [[Paragraph("Status", s["header_cell"]), Paragraph("Count", s["header_cell"])]]
    for status, count in sorted(status_counts.items(), key=lambda kv: -kv[1]):
        count_rows.append([Paragraph(_e(status), s["cell"]), Paragraph(str(count), s["cell_right"])])
    counts_table = Table(count_rows, colWidths=[4.5 * cm, 2.5 * cm])
    counts_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), TITLE_COLOR),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DDE1E6")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))

    side_by_side = Table(
        [[Image(chart_path, width=8 * cm, height=8 * cm), counts_table]],
        colWidths=[8.5 * cm, 8.5 * cm],
    )
    side_by_side.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story.append(side_by_side)

    # ---- Estimated value by currency ----
    story.append(Paragraph("Estimated Value by Currency", s["section"]))
    value_rows = [[Paragraph("Currency", s["header_cell"]), Paragraph("Total Value", s["header_cell"])]]
    for currency, value in sorted(summary["value_by_currency"].items()):
        label = currency if currency and currency != "?" else "(No currency set)"
        value_rows.append([Paragraph(_e(label), s["cell"]), Paragraph(f"{value:,.2f}", s["cell_right"])])
    value_table = Table(value_rows, colWidths=[8.5 * cm, 8.5 * cm])
    value_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), TITLE_COLOR),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DDE1E6")),
    ]))
    story.append(value_table)

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)

    try:
        os.remove(chart_path)
    except OSError:
        pass
    return output_path


def export_stale_items_to_pdf(db, stale_items, output_path, scope_label):
    """Just the "Possibly Forgotten" item list, as its own document, so
    it can be shared on its own without the rest of the dashboard."""
    s = _styles()
    doc = SimpleDocTemplate(
        output_path, pagesize=landscape(A4),
        topMargin=3.0 * cm, bottomMargin=1.3 * cm, leftMargin=1 * cm, rightMargin=1 * cm,
    )
    story = []
    story.append(Paragraph("Possibly Forgotten Items", s["title"]))
    story.append(Paragraph(
        f"{_e(scope_label)}  \u2014  still \u201cNot requested\u201d with no activity for 14+ days  \u2014  "
        f"Generated {datetime.now().strftime('%Y-%m-%d')}", s["subtitle"]
    ))
    story.append(Spacer(1, 0.5 * cm))

    if not stale_items:
        story.append(Paragraph("Nothing forgotten \u2014 every item has had recent activity.", s["cell"]))
    else:
        headers = ["Item Name", "Project", "Area", "Days Untouched"]
        rows = [[Paragraph(h, s["header_cell"]) for h in headers]]
        for it in stale_items:
            rows.append([
                Paragraph(_e(it["item_name"]), s["cell"]),
                Paragraph(_e(it["project_name"]), s["cell"]),
                Paragraph(_e(it["pump_station"] or "-"), s["cell"]),
                Paragraph(str(it["days_stale"]), s["cell_right"]),
            ])
        table = Table(rows, colWidths=[9 * cm, 6 * cm, 6 * cm, 3.5 * cm], repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), TITLE_COLOR),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DDE1E6")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F7FA")]),
        ]))
        story.append(table)

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return output_path
