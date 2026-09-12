"""
pdf_export.py
Generates a professional PDF summary report for one project:
header info, a status pie chart, and a full items table with totals.

Every table cell — not just the item name — is wrapped in a reportlab
Paragraph so long text wraps within its own cell instead of being clipped
or bleeding into the next column (the bug in the previous version).
"""

import os
import tempfile

import config as _config

import matplotlib
matplotlib.use("Agg")  # no GUI backend needed for chart generation
import matplotlib.pyplot as plt

from xml.sax.saxutils import escape as _xml_escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, PageBreak
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

from constants import STATUS_COLORS, STATUS_TEXT_COLORS, is_over_supplied, \
    remaining_to_deliver, OVER_SUPPLY_COLOR, OVER_SUPPLY_TEXT, POST_DELIVERY_CATEGORIES

FONT_NAME = "Helvetica"

import logging

logger = logging.getLogger(__name__)

# Arabic support in PDFs: reportlab's built-in Helvetica has no Arabic
# glyphs, and reportlab does no complex text layout (no glyph joining,
# no bidi reordering) — so Arabic item names would render as missing or
# disconnected letters. When an Arabic-capable Windows font (Arial or
# Segoe UI) is present and the two small pure-Python helpers
# (arabic-reshaper + python-bidi) are installed, Arabic text is shaped
# and rendered properly. Otherwise we degrade gracefully to the old
# behavior and log a hint once.
_ARABIC_RANGES = (
    ("\u0600", "\u06FF"), ("\u0750", "\u077F"), ("\u08A0", "\u08FF"),
    ("\uFB50", "\uFDFF"), ("\uFE70", "\uFEFF"),
)

_arabic_font_pair = None
_arabic_setup_tried = False


def _has_arabic(value):
    s = str(value or "")
    return any(lo <= ch <= hi for ch in s for lo, hi in _ARABIC_RANGES)


def _setup_arabic_fonts():
    """Registers an Arabic-capable Windows font with reportlab (once).
    Returns (regular, bold) font names, or None when unavailable."""
    global _arabic_font_pair, _arabic_setup_tried
    if _arabic_setup_tried:
        return _arabic_font_pair
    _arabic_setup_tried = True
    try:
        import arabic_reshaper  # noqa: F401 — optional dependency
        from bidi.algorithm import get_display  # noqa: F401
    except ImportError:
        logger.warning(
            "Arabic PDF text is disabled: install 'arabic-reshaper' and "
            "'python-bidi' to render Arabic item names correctly in PDFs."
        )
        return None
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    win_fonts = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    for regular, bold in (("arial.ttf", "arialbd.ttf"), ("segoeui.ttf", "segoeuib.ttf")):
        reg_path = os.path.join(win_fonts, regular)
        bold_path = os.path.join(win_fonts, bold)
        if os.path.isfile(reg_path) and os.path.isfile(bold_path):
            try:
                pdfmetrics.registerFont(TTFont("PT-Arabic", reg_path))
                pdfmetrics.registerFont(TTFont("PT-Arabic-Bold", bold_path))
                pdfmetrics.registerFontFamily(
                    "PT-Arabic", normal="PT-Arabic", bold="PT-Arabic-Bold",
                    italic="PT-Arabic", boldItalic="PT-Arabic-Bold",
                )
                _arabic_font_pair = ("PT-Arabic", "PT-Arabic-Bold")
                return _arabic_font_pair
            except Exception:
                logger.warning("Could not register Arabic font %s", reg_path, exc_info=True)
    return None


def _shape_arabic(value):
    """Reshapes + bidi-reorders Arabic text so reportlab renders it
    connected and in the correct visual order."""
    s = str(value) if value is not None else ""
    if not _has_arabic(s) or not _setup_arabic_fonts():
        return s
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(s))
    except Exception:
        return s


def _e(value):
    """Escape a value for safe use inside a reportlab Paragraph (which
    parses its input as XML/HTML-like markup — an unescaped '&' as in
    "O&M Manual", '<' or '>' would corrupt the rendered text), shaping
    any Arabic content first so it renders correctly."""
    if value is None:
        return ""
    return _xml_escape(_shape_arabic(str(value)))


def _pie_chart_from_counts(counts, title="Items by Status"):
    """Renders a status-breakdown pie chart from a pre-computed
    {status: count} dict and returns the path to a temporary PNG —
    shared by the per-project PDF report and the Dashboard PDF report so
    both always look identical."""
    if not counts:
        counts = {"No items": 1}

    fig, ax = plt.subplots(figsize=(4.5, 4.5))
    palette = [STATUS_COLORS.get(s, "#94A3B8") for s in counts.keys()]
    ax.pie(
        counts.values(),
        labels=counts.keys(),
        autopct="%1.0f%%",
        startangle=90,
        colors=palette,
        textprops={"fontsize": 9},
        wedgeprops={"edgecolor": "white", "linewidth": 1},
    )
    ax.set_title(title, fontsize=12, fontweight="bold")
    ax.axis("equal")

    tmp = tempfile.NamedTemporaryFile(suffix="_status_pie.png", delete=False)
    tmp_path = tmp.name
    tmp.close()
    fig.savefig(tmp_path, dpi=150, bbox_inches="tight", transparent=True)
    plt.close(fig)
    return tmp_path


def _build_status_pie_chart(items):
    counts = {}
    for it in items:
        status = it["status"] or "Not requested"
        counts[status] = counts.get(status, 0) + 1
    return _pie_chart_from_counts(counts, title="Items by Status")


def export_project_to_pdf(db, project_id, output_path):
    project = db.get_project(project_id)
    items = db.get_items(project_id)

    all_attachments = db.get_all_attachments_for_project(project_id)
    post_delivery_categories_by_item = {}
    for a in all_attachments:
        if a["category"] in POST_DELIVERY_CATEGORIES:
            post_delivery_categories_by_item.setdefault(a["item_id"], set()).add(a["category"])

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("TitleCenter", parent=styles["Title"], alignment=TA_CENTER, fontSize=18,
                                  textColor=colors.HexColor("#1F4E78"))
    subtitle_style = ParagraphStyle("Subtitle", parent=styles["Normal"], alignment=TA_CENTER, fontSize=10,
                                     textColor=colors.grey)
    section_style = ParagraphStyle("Section", parent=styles["Heading2"], fontSize=13, spaceBefore=12, spaceAfter=6,
                                    textColor=colors.HexColor("#1F4E78"))
    cell_style = ParagraphStyle("Cell", parent=styles["Normal"], fontSize=8, leading=10, alignment=TA_LEFT,
                                 wordWrap="CJK")
    cell_style_right = ParagraphStyle("CellRight", parent=cell_style, alignment=TA_RIGHT)
    cell_style_center = ParagraphStyle("CellCenter", parent=cell_style, alignment=TA_CENTER)
    header_cell_style = ParagraphStyle("HeaderCell", parent=cell_style_center, textColor=colors.white,
                                        fontName="Helvetica-Bold", fontSize=8.5)

    # Use the Arabic-capable font for every paragraph when available —
    # Arial/Segoe UI render Latin text just as well, so this is safe.
    arabic_fonts = _setup_arabic_fonts()
    if arabic_fonts:
        regular, bold = arabic_fonts
        for _st in (title_style, subtitle_style, section_style, cell_style,
                    cell_style_right, cell_style_center, header_cell_style):
            _st.fontName = bold if _st.fontName.endswith("-Bold") else regular

    doc = SimpleDocTemplate(
        output_path, pagesize=landscape(A4),
        # Generous top margin: the company-logo letterhead is drawn at the
        # top-right of EVERY page, and the repeated table header must never
        # collide with it.
        topMargin=3.0 * cm, bottomMargin=1.3 * cm,
        leftMargin=1 * cm, rightMargin=1 * cm,
    )

    story = []
    story.append(Paragraph(_e(project["name"]), title_style))
    subtitle = (
        f"Location: {_e(project['location']) or '-'}   |   Contractor: {_e(project['contractor']) or '-'}"
        f"   |   Default Currency: {_e(project['currency']) or '-'}   |   Generated: "
        f"{__import__('datetime').datetime.now().strftime('%Y-%m-%d')}"
    )
    story.append(Paragraph(subtitle, subtitle_style))
    story.append(Spacer(1, 0.5 * cm))

    # ---- Summary numbers ----
    total_items = len(items)
    total_cost = sum((it["total_quantity"] or 0) * (it["unit_cost"] or 0) for it in items)
    delivered_count = sum(1 for it in items if (it["status"] or "") == "Delivered")
    over_count = sum(1 for it in items if is_over_supplied(it["total_quantity"], it["delivered_quantity"]))

    summary_labels = ["Total Items", "Delivered", "Over-supplied", "Estimated Total Cost"]
    summary_values = [str(total_items), str(delivered_count), str(over_count),
                       f"{total_cost:,.2f} {_e(project['currency']) or ''}"]
    summary_data = [
        [Paragraph(s, header_cell_style) for s in summary_labels],
        [Paragraph(s, ParagraphStyle("SumVal", parent=cell_style_center, fontSize=13, fontName="Helvetica-Bold"))
         for s in summary_values],
    ]
    summary_table = Table(summary_data, colWidths=[6.5 * cm] * 4)
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E78")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#C9CDD3")),
        ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#1F4E78")),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 0.7 * cm))

    # ---- Pie chart ----
    story.append(Paragraph("Status Overview", section_style))
    chart_path = _build_status_pie_chart(items)
    story.append(Image(chart_path, width=8.5 * cm, height=8.5 * cm))
    story.append(Spacer(1, 0.6 * cm))

    # ---- Items table ----
    # The details table always starts on a fresh page: page 1 stays a clean
    # cover (title + summary + status chart), and the wide table gets the
    # full sheet from page 2 onward.
    story.append(PageBreak())
    story.append(Paragraph("Item Details", section_style))
    table_header = ["#", "Item Name", "Area", "Supplier", "Unit", "Ccy",
                     "Total", "Delivered", "Remaining", "Unit Cost", "Total Cost", "Status", "Post-Del. Docs"]
    table_data = [[Paragraph(h, header_cell_style) for h in table_header]]

    n_post_categories = len(POST_DELIVERY_CATEGORIES)
    row_styles = []  # extra TableStyle commands for per-row coloring
    for row_idx, it in enumerate(items, start=1):
        total_qty = it["total_quantity"] or 0
        delivered_qty = it["delivered_quantity"] or 0
        over = is_over_supplied(total_qty, delivered_qty)
        status_bg = OVER_SUPPLY_COLOR if over else STATUS_COLORS.get(it["status"], "#FFFFFF")
        status_fg = OVER_SUPPLY_TEXT if over else STATUS_TEXT_COLORS.get(it["status"], "#1E293B")
        status_label = f"{it['status']} (!)" if over else it["status"]

        status_style = ParagraphStyle(
            f"Status{row_idx}", parent=cell_style_center, textColor=colors.HexColor(status_fg),
            fontName="Helvetica-Bold",
        )

        docs_present = post_delivery_categories_by_item.get(it["id"], set())
        docs_label = f"{len(docs_present)}/{n_post_categories}"
        docs_style = ParagraphStyle(
            f"Docs{row_idx}", parent=cell_style_center,
            textColor=colors.HexColor("#0E9F82") if docs_present else colors.HexColor("#9AA3B8"),
            fontName="Helvetica-Bold" if docs_present else "Helvetica",
        )

        table_data.append([
            Paragraph(str(it["sort_order"] or row_idx), cell_style_center),
            Paragraph(_e(it["item_name"]), cell_style),
            Paragraph(_e(it["pump_station"]), cell_style),
            Paragraph(_e(it["supplier_name"]) or "-", cell_style),
            Paragraph(_e(it["unit"]), cell_style_center),
            Paragraph(_e(it["currency"]) or _e(project["currency"]), cell_style_center),
            Paragraph(f"{total_qty:,.2f}", cell_style_right),
            Paragraph(f"{delivered_qty:,.2f}", cell_style_right),
            Paragraph(f"{remaining_to_deliver(total_qty, delivered_qty):,.2f}", cell_style_right),
            Paragraph(f"{it['unit_cost'] or 0:,.2f}", cell_style_right),
            Paragraph(f"{total_qty * (it['unit_cost'] or 0):,.2f}", cell_style_right),
            Paragraph(_e(status_label), status_style),
            Paragraph(docs_label, docs_style),
        ])
        table_row = row_idx  # header is row 0
        row_styles.append(("BACKGROUND", (11, table_row), (11, table_row), colors.HexColor(status_bg)))
        if over:
            row_styles.append(("BACKGROUND", (0, table_row), (10, table_row), colors.HexColor("#F6F1FC")))
            row_styles.append(("BACKGROUND", (12, table_row), (12, table_row), colors.HexColor("#F6F1FC")))

    col_widths = [0.9 * cm, 5 * cm, 2.6 * cm, 2.6 * cm, 1.2 * cm, 1.2 * cm,
                  1.8 * cm, 1.8 * cm, 1.9 * cm, 1.9 * cm, 2.1 * cm, 2.9 * cm, 2 * cm]
    items_table = Table(table_data, colWidths=col_widths, repeatRows=1)
    base_style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E78")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C9CDD3")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F5FB")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    items_table.setStyle(TableStyle(base_style + row_styles))
    story.append(items_table)

    if any(it["variance_note"] for it in items):
        story.append(Spacer(1, 0.4 * cm))
        story.append(Paragraph("Over-supply Notes", section_style))
        for it in items:
            if it["variance_note"]:
                story.append(Paragraph(f"<b>{_e(it['item_name'])}:</b> {_e(it['variance_note'])}", cell_style))

    items_with_docs = [it for it in items if post_delivery_categories_by_item.get(it["id"])]
    if items_with_docs:
        story.append(Spacer(1, 0.4 * cm))
        story.append(Paragraph("Post-Delivery Documents Summary", section_style))
        for it in items_with_docs:
            present = sorted(post_delivery_categories_by_item[it["id"]])
            missing = [c for c in POST_DELIVERY_CATEGORIES if c not in present]
            line = f"<b>{_e(it['item_name'])}:</b> {_e(', '.join(present))}"
            if missing:
                line += f"  <font color='#9AA3B8'>(missing: {_e(', '.join(missing))})</font>"
            story.append(Paragraph(line, cell_style))

    page_w, page_h = landscape(A4)

    def _footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont(FONT_NAME, 8)
        canvas.setFillColor(colors.grey)
        canvas.drawRightString(page_w - 1 * cm, 0.7 * cm, f"Page {doc_.page}")
        canvas.drawString(1 * cm, 0.7 * cm, "Project Tracker")
        # Company logo letterhead (top-right corner), when the user set one
        # via File -> Company Logo... Never blocks the report on failure.
        logo = _config.logo_path()
        if logo:
            try:
                canvas.drawImage(
                    logo, page_w - 4.1 * cm, page_h - 2.7 * cm,
                    width=3.1 * cm, height=2.0 * cm,
                    preserveAspectRatio=True, mask="auto",
                )
            except Exception:
                logger.warning("Could not draw company logo on PDF", exc_info=True)
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)

    try:
        os.remove(chart_path)
    except OSError:
        pass

    return output_path
