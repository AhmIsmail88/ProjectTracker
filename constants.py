"""
constants.py
Single source of truth for all shared constants used across the app.
"""

APP_VERSION = "2.32"

# ---- Status definitions ----
# Order matters: this is the order shown in combo boxes & reports.
# Colors are a refined, professional palette (soft backgrounds + strong
# accent text so status is readable at a glance in both themes).
STATUSES = {
    "Not requested":        {"color": "#E5E7EB", "text": "#374151", "order": 0},
    "Partially Requested":  {"color": "#FFF0D9", "text": "#B45309", "order": 1},
    "Requested":            {"color": "#FEF3C7", "text": "#92400E", "order": 2},
    "PO Issued":            {"color": "#DBEAFE", "text": "#1E40AF", "order": 3},
    "Partially Delivered":  {"color": "#FFE3C2", "text": "#9A5B13", "order": 4},
    "Delivered":            {"color": "#D1FAE5", "text": "#065F46", "order": 5},
    "On Hold":              {"color": "#FEE2E2", "text": "#991B1B", "order": 6},
}

# Special highlight used when delivered_quantity > total_quantity
# (over-supply). This overrides the normal status color in the table.
OVER_SUPPLY_COLOR = "#EDE1FB"
OVER_SUPPLY_TEXT = "#5B21B6"
DELIVERED_NO_REQUEST_COLOR = "#FEE2E2"
DELIVERED_NO_REQUEST_TEXT = "#B91C1C"
OVER_REQUEST_COLOR = "#FFEDD5"
OVER_REQUEST_TEXT = "#9A3412"

STATUS_OPTIONS = list(STATUSES.keys())
STATUS_COLORS = {name: info["color"] for name, info in STATUSES.items()}
STATUS_TEXT_COLORS = {name: info["text"] for name, info in STATUSES.items()}

# Attachment categories, split into two logical groups:
#  - pre/during-procurement documents (existing)
#  - post-delivery / handover documents (added per user request)
# The two groups only differ in one behavior: uploading a post-delivery
# category triggers a confirmation if the item isn't marked "Delivered"
# yet (see ui/dialogs.py AttachmentsDialog._upload_file).
PRE_DELIVERY_CATEGORIES = ["PR", "PO", "Reference"]
POST_DELIVERY_CATEGORIES = [
    "Warranty", "O&M Manual", "Test Certificate", "As-Built Drawing",
    "Spare Parts List", "MIR", "Invoice",
]
ATTACHMENT_CATEGORIES = PRE_DELIVERY_CATEGORIES + POST_DELIVERY_CATEGORIES
POST_DELIVERY_CATEGORIES_SET = frozenset(POST_DELIVERY_CATEGORIES)

# ---- Currencies offered in the item/project currency dropdown ----
CURRENCIES = ["SAR", "USD", "EUR", "AED", "EGP", "GBP", "KWD", "QAR", "BHD", "OMR"]

# ---- Database column whitelists (for safe dynamic UPDATE) ----
ALLOWED_PROJECT_COLS = frozenset({
    "name", "location", "contractor", "project_number", "currency", "notes", "group_id",
})

ALLOWED_SUPPLIER_COLS = frozenset({
    "name", "contact_person", "phone", "email", "notes",
})

ALLOWED_ITEM_COLS = frozenset({
    "item_name", "pump_station", "supplier_id", "unit",
    "total_quantity", "requested_quantity", "delivered_quantity",
    "unit_cost", "currency", "remarks", "status", "last_updated",
    "manual_hold", "po_issued", "variance_note",
})


def compute_status(total_qty, requested_qty, delivered_qty, manual_hold=False, po_issued=False):
    """Central rule for automatically deriving an item's status from its
    quantities, so the UI never has to duplicate this logic.

    Priority:
      1. Manual "On Hold" always wins (explicit human override).
      2. Fully or over delivered -> Delivered.
      3. Some delivered but not all -> Partially Delivered.
      4. PO marked as issued but nothing delivered yet -> PO Issued.
      5. Something requested:
           - less than the total (البند) -> Partially Requested.
           - requested amount reaches the total -> Requested.
      6. Nothing requested yet -> Not requested.
    """
    total_qty = total_qty or 0
    requested_qty = requested_qty or 0
    delivered_qty = delivered_qty or 0

    if manual_hold:
        return "On Hold"
    if total_qty > 0 and delivered_qty >= total_qty:
        return "Delivered"
    if delivered_qty > 0:
        return "Partially Delivered"
    if po_issued:
        return "PO Issued"
    if requested_qty > 0:
        if total_qty > 0 and requested_qty < total_qty:
            return "Partially Requested"
        return "Requested"
    return "Not requested"


def is_over_supplied(total_qty, delivered_qty):
    total_qty = total_qty or 0
    delivered_qty = delivered_qty or 0
    return delivered_qty > total_qty + 1e-9


def is_delivered_without_request(requested_qty, delivered_qty):
    """Flags a data-entry inconsistency worth a warning: a delivered
    quantity was recorded even though the item was never marked as
    requested at all — delivery normally follows a request."""
    requested_qty = requested_qty or 0
    delivered_qty = delivered_qty or 0
    return delivered_qty > 0 and requested_qty <= 0


def is_over_requested(total_qty, requested_qty):
    """Flags requesting more than the item's whole scope — worth a
    warning, the same way requesting/receiving too much of anything
    else would be."""
    total_qty = total_qty or 0
    requested_qty = requested_qty or 0
    return requested_qty > total_qty + 1e-9


def remaining_to_request(total_qty, requested_qty):
    return max((total_qty or 0) - (requested_qty or 0), 0)


def remaining_to_deliver(total_qty, delivered_qty):
    return max((total_qty or 0) - (delivered_qty or 0), 0)


# --------------------------------------------------------------------------- #
# Theme state for directly-painted table cells
# --------------------------------------------------------------------------- #
# Status chips and the amber "needs attention" cells are painted as cell
# brushes, not through the stylesheet, so they cannot follow the QSS theme on
# their own. main.py calls set_theme() whenever the theme changes, and the
# Items screen re-styles its rows so the chip colors never lag behind the
# rest of the UI.
_ACTIVE_THEME = "dark"


def set_theme(theme):
    global _ACTIVE_THEME
    _ACTIVE_THEME = "light" if theme == "light" else "dark"


def get_theme():
    return _ACTIVE_THEME


# Dark-theme equivalents of the pastel status chips: a deep tinted surface
# with a bright, readable label. Same semantics as the light palette
# (Delivered stays green, On Hold stays red, and so on).
_DARK_STATUS_CHIPS = {
    "Not requested":       ("#1E2A3D", "#A9B8CE"),
    "Partially Requested": ("#3A2E14", "#F0C46B"),
    "Requested":           ("#402F10", "#F5CC69"),
    "PO Issued":           ("#15304F", "#7FB6F5"),
    "Partially Delivered": ("#3B2A14", "#F0A860"),
    "Delivered":           ("#123A2C", "#5FD9A6"),
    "On Hold":             ("#3A1B1F", "#F29494"),
}
_DARK_STATUS_FALLBACK = ("#1E2A3D", "#A9B8CE")

_DARK_SPECIAL_CHIPS = {
    "over_supply":  ("#2E2350", "#C4B0FB"),
    "no_request":   ("#3A1B1F", "#F29494"),
    "over_request": ("#3A2716", "#F0A860"),
}

_LIGHT_WARNING_CHIP = ("#FEF3C7", "#78350F")
_DARK_WARNING_CHIP = ("#3A2E14", "#F0C46B")


def status_chip_colors(status, theme=None):
    """(background, foreground) for a Status chip.

    On the light theme this returns exactly the original pastel values, so
    light mode is visually unchanged; on the dark theme it returns the
    deep-tinted equivalent.
    """
    theme = theme or _ACTIVE_THEME
    if theme == "light":
        return (STATUS_COLORS.get(status, "#FFFFFF"),
                STATUS_TEXT_COLORS.get(status, "#1E293B"))
    return _DARK_STATUS_CHIPS.get(status, _DARK_STATUS_FALLBACK)


def special_chip_colors(kind, theme=None):
    """(background, foreground) for the quantity-warning chips that override
    the normal status colour: over-supply, delivered-without-request, and
    over-request."""
    theme = theme or _ACTIVE_THEME
    if theme == "light":
        light = {
            "over_supply":  (OVER_SUPPLY_COLOR, OVER_SUPPLY_TEXT),
            "no_request":   (DELIVERED_NO_REQUEST_COLOR, DELIVERED_NO_REQUEST_TEXT),
            "over_request": (OVER_REQUEST_COLOR, OVER_REQUEST_TEXT),
        }
        return light.get(kind, light["over_supply"])
    return _DARK_SPECIAL_CHIPS.get(kind, _DARK_SPECIAL_CHIPS["over_supply"])


def warning_chip_colors(kind, theme=None):
    """(background, foreground) for the amber "needs attention" cells
    (missing unit cost / missing PR-PO). Light mode keeps the original amber
    exactly, so nothing changes there."""
    theme = theme or _ACTIVE_THEME
    return _LIGHT_WARNING_CHIP if theme == "light" else _DARK_WARNING_CHIP


# --------------------------------------------------------------------------- #
# Delivery-ratio chips (Projects screen "Delivered %" column)
# --------------------------------------------------------------------------- #
# Three bands rather than a continuous scale: a percentage is read as
# "healthy / in progress / behind", and a discrete band keeps the list
# scannable instead of a gradient of near-identical colours.
_LIGHT_RATIO_CHIPS = {
    "high": ("#D1FAE5", "#065F46"),
    "mid":  ("#DBEAFE", "#1E40AF"),
    "low":  ("#FEF3C7", "#92400E"),
}
_DARK_RATIO_CHIPS = {
    "high": ("#123A2C", "#5FD9A6"),
    "mid":  ("#15304F", "#7FB6F5"),
    "low":  ("#3A2E14", "#F0C46B"),
}


def ratio_band(percent):
    """>= 80% delivered is healthy, >= 40% is in progress, below is behind."""
    if percent >= 80:
        return "high"
    if percent >= 40:
        return "mid"
    return "low"


def ratio_chip_colors(percent, theme=None):
    """(background, foreground) for a delivery-percentage cell."""
    theme = theme or _ACTIVE_THEME
    table = _LIGHT_RATIO_CHIPS if theme == "light" else _DARK_RATIO_CHIPS
    return table[ratio_band(percent)]


def chart_label_color(theme=None):
    """Foreground colour for text drawn *inside* a chart (the donut total).

    Charts paint with QPainter rather than the stylesheet, so they cannot
    inherit the theme colour; without this the text would stay the default
    dark colour and vanish on the dark theme."""
    theme = theme or _ACTIVE_THEME
    return "#E8EFF9" if theme == "dark" else "#0E1B30"
