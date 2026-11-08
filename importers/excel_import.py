"""
importers/excel_import.py
Bulk-imports items (and matches suppliers by name) from an existing Excel
spreadsheet into a project — lets someone switch from a spreadsheet-based
tracker to this app without retyping everything by hand.

Design: this module only does the mechanical part (read rows, parse them
per a given column mapping, write items). The actual field mapping is
always chosen/reviewed by the user in ui/import_excel_dialog.py — a
spreadsheet's column names never match ours exactly, and auto-guessing
silently would risk importing the wrong data into the wrong field.

Supplier names that don't already exist are left unmatched (item is
imported with no supplier set) rather than auto-created, so imports never
create a pile of messy near-duplicate supplier records from typos or
inconsistent spelling in someone's old spreadsheet.
"""

import openpyxl
import math
from itertools import zip_longest
from decimal import Decimal, InvalidOperation

IMPORT_FIELDS = [
    ("item_name", "Item Name", True),
    ("pump_station", "Pump Station / Area", False),
    ("supplier", "Supplier Name", False),
    ("unit", "Unit", False),
    ("currency", "Currency", False),
    ("total_quantity", "Total Quantity", False),
    ("requested_quantity", "Requested Quantity", False),
    ("delivered_quantity", "Delivered Quantity", False),
    ("unit_cost", "Unit Cost", False),
    ("remarks", "Remarks", False),
]

# Lower-cased keyword hints used only to *pre-select* a best-guess mapping
# in the UI — the user always sees and can override the guess before
# anything is imported.
_AUTO_MAP_HINTS = {
    "item_name": ["item name", "item", "description", "material", "name"],
    "pump_station": ["area", "location", "pump station", "station", "zone"],
    "supplier": ["supplier", "vendor", "manufacturer"],
    "unit": ["unit", "uom"],
    "currency": ["currency", "ccy"],
    "total_quantity": ["total qty", "total quantity", "boq qty", "qty", "quantity"],
    "requested_quantity": ["requested", "ordered qty", "po qty"],
    "delivered_quantity": ["delivered", "received qty"],
    "unit_cost": ["unit cost", "unit price", "rate", "price"],
    "remarks": ["remarks", "notes", "comment"],
}


def read_sheet_names(file_path):
    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    names = wb.sheetnames
    wb.close()
    return names


def read_headers(file_path, sheet_name=None):
    """Returns (headers, header_row_index). Reads the first few rows and
    picks the one with the most non-empty text cells as the header row —
    tolerates a title row (e.g. a merged project-name cell) sitting above
    the real header row, which is common in hand-built BOQ sheets."""
    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    ws = wb[sheet_name] if sheet_name else wb.active

    best_row_idx, best_row, best_score = 1, [], -1
    max_scan = min(6, ws.max_row or 1)
    for row_idx, row in enumerate(ws.iter_rows(min_row=1, max_row=max_scan, values_only=True), start=1):
        score = sum(1 for c in row if isinstance(c, str) and c.strip())
        if score > best_score:
            best_score = score
            best_row_idx = row_idx
            best_row = row

    headers = [str(c).strip() if c is not None else "" for c in best_row]
    wb.close()
    return headers, best_row_idx


def guess_mapping(headers):
    """Best-effort auto mapping from detected headers to our field keys —
    purely a starting point the user reviews/edits in the UI, never
    applied silently."""
    mapping = {}
    used_headers = set()
    lower_headers = [(h, h.lower()) for h in headers if h]
    for field_key, _label, _required in IMPORT_FIELDS:
        hints = _AUTO_MAP_HINTS.get(field_key, [])
        for header, lower in lower_headers:
            if header in used_headers:
                continue
            if any(hint in lower for hint in hints):
                mapping[field_key] = header
                used_headers.add(header)
                break
    return mapping


def _parse_number(value):
    if value is None or value == "":
        return 0.0
    try:
        number = float(str(value).replace(",", "").strip())
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid number: {value!r}") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"Expected a finite, non-negative number: {value!r}")
    return number


def _row_to_record(row, col_index, mapping):
    record = {}
    for field_key, _label, _req in IMPORT_FIELDS:
        header = mapping.get(field_key)
        if header and header in col_index and col_index[header] < len(row):
            record[field_key] = row[col_index[header]]
        else:
            record[field_key] = None
    return record


def preview_rows(file_path, sheet_name, header_row_idx, mapping, limit=10):
    """Returns up to *limit* mapped rows (list of dicts) for a review
    table, without writing anything to the database."""
    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    ws = wb[sheet_name] if sheet_name else wb.active
    headers, _ = read_headers(file_path, sheet_name)
    col_index = {h: i for i, h in enumerate(headers)}

    rows = []
    for row in ws.iter_rows(min_row=header_row_idx + 1, values_only=True):
        if len(rows) >= limit:
            break
        if all(c is None or str(c).strip() == "" for c in row):
            continue
        rows.append(_row_to_record(row, col_index, mapping))
    wb.close()
    return rows


def _is_uncached_formula(raw_value):
    """A formula cell whose computed result was never saved in the file.

    openpyxl cannot calculate formulas; with data_only=True it returns the
    result Excel stored when the file was last saved. Files written by other
    tools (scripts, some web exports) often carry the formula only - the
    value then reads as empty and would silently import as 0."""
    if isinstance(raw_value, str):
        return raw_value.startswith("=")
    return type(raw_value).__name__ in ("ArrayFormula", "DataTableFormula")


_FORMULA_CHECKED_FIELDS = frozenset({
    "item_name", "total_quantity", "requested_quantity", "delivered_quantity", "unit_cost",
})


def _iter_value_and_formula_rows(file_path, sheet_name, min_row):
    """Yields (row_number, values, raw_formulas) for every row from min_row,
    reading the file twice in read-only mode: once for saved values, once
    for the formulas themselves."""
    values_wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    formulas_wb = openpyxl.load_workbook(file_path, read_only=True, data_only=False)
    try:
        values_ws = values_wb[sheet_name] if sheet_name else values_wb.active
        formulas_ws = formulas_wb[sheet_name] if sheet_name else formulas_wb.active
        pairs = zip_longest(
            values_ws.iter_rows(min_row=min_row, values_only=True),
            formulas_ws.iter_rows(min_row=min_row, values_only=True),
            fillvalue=(),
        )
        for row_num, (values, raw) in enumerate(pairs, start=min_row):
            yield row_num, tuple(values or ()), tuple(raw or ())
    finally:
        values_wb.close()
        formulas_wb.close()


def _existing_key(name, area, unit):
    return (_norm_text(name), _norm_text(area), _norm_text(unit))


def _parse_item_rows(db, project_id, file_path, sheet_name, header_row_idx, mapping):
    """Reads and validates every row WITHOUT writing anything.

    Returns (records, skipped, unmatched_suppliers) where each record holds
    the keyword arguments for db.add_item plus its "_row" number."""
    project = db.get_project(project_id)
    suppliers_by_name = {s["name"].strip().lower(): s["id"] for s in db.get_suppliers()}
    headers, _ = read_headers(file_path, sheet_name)
    col_index = {h: i for i, h in enumerate(headers)}

    records = []
    skipped = []
    unmatched_suppliers = set()

    for row_num, row, raw_row in _iter_value_and_formula_rows(file_path, sheet_name, header_row_idx + 1):
        if all(c is None or str(c).strip() == "" for c in row) and                 not any(_is_uncached_formula(c) for c in raw_row):
            continue

        # Only fields where an empty value would silently mean something
        # (no name -> row lost, no number -> 0) are checked.
        uncached = [
            header for field_key, header in mapping.items()
            if field_key in _FORMULA_CHECKED_FIELDS and header in col_index and col_index[header] < len(raw_row)
            and _is_uncached_formula(raw_row[col_index[header]])
            and (col_index[header] >= len(row) or row[col_index[header]] is None)
        ]
        if uncached:
            skipped.append(
                f"Row {row_num}, column {', '.join(uncached)}: formula without a saved value "
                f"- open the file in Excel, save it, then import again"
            )
            continue

        record = _row_to_record(row, col_index, mapping)

        item_name = record["item_name"]
        item_name = str(item_name).strip() if item_name is not None else ""
        if not item_name:
            skipped.append(f"Row {row_num}: no item name")
            continue

        supplier_id = None
        supplier_raw = record["supplier"]
        if supplier_raw:
            key = str(supplier_raw).strip().lower()
            if key in suppliers_by_name:
                supplier_id = suppliers_by_name[key]
            else:
                unmatched_suppliers.add(str(supplier_raw).strip())

        currency = record["currency"]
        currency = str(currency).strip() if currency else project["currency"]

        numbers = {}
        try:
            for field in ("total_quantity", "requested_quantity", "delivered_quantity", "unit_cost"):
                numbers[field] = _parse_number(record[field])
        except ValueError as exc:
            skipped.append(f"Row {row_num}, column {mapping.get(field, field)}: {exc}")
            continue

        records.append(dict(
            _row=row_num,
            item_name=item_name,
            pump_station=str(record["pump_station"] or "").strip(),
            supplier_id=supplier_id,
            unit=str(record["unit"] or "").strip(),
            currency=currency,
            remarks=str(record["remarks"] or "").strip(),
            **numbers,
        ))
    return records, skipped, unmatched_suppliers


def count_existing_rows(db, project_id, file_path, sheet_name, header_row_idx, mapping):
    """How many valid rows of the file describe an item the project already
    has (same name + area + unit) - shown before importing, so loading the
    same sheet twice does not silently double every quantity."""
    records, _skipped, _unmatched = _parse_item_rows(
        db, project_id, file_path, sheet_name, header_row_idx, mapping)
    existing = {_existing_key(it["item_name"], it["pump_station"], it["unit"])
                for it in db.get_items(project_id)}
    return sum(1 for r in records
               if _existing_key(r["item_name"], r["pump_station"], r["unit"]) in existing)


def import_items_from_excel(db, project_id, file_path, sheet_name, header_row_idx, mapping,
                            skip_existing=False):
    """Performs the actual import. Returns a result dict:
    {"imported": int, "skipped": [reasons...], "unmatched_suppliers": [names...],
     "skipped_existing": int}.

    All-or-nothing: the whole file is read and validated first, then every
    item is written in ONE transaction - a failure part-way through leaves
    the project exactly as it was. skip_existing=True leaves out rows that
    match an item the project already has (same name + area + unit)."""
    records, skipped, unmatched_suppliers = _parse_item_rows(
        db, project_id, file_path, sheet_name, header_row_idx, mapping)

    skipped_existing = 0
    if skip_existing:
        existing = {_existing_key(it["item_name"], it["pump_station"], it["unit"])
                    for it in db.get_items(project_id)}
        kept = []
        for r in records:
            if _existing_key(r["item_name"], r["pump_station"], r["unit"]) in existing:
                skipped_existing += 1
            else:
                kept.append(r)
        records = kept

    with db.transaction():
        for record in records:
            fields = {k: v for k, v in record.items() if k != "_row"}
            db.add_item(project_id, **fields)

    return {
        "imported": len(records),
        "skipped": skipped,
        "unmatched_suppliers": sorted(unmatched_suppliers),
        "skipped_existing": skipped_existing,
    }


def _norm_text(value):
    return " ".join(str(value or "").split()).casefold()


def import_cost_updates_from_excel(db, file_path, dry_run=False):
    """Reads back a file produced by export_items_for_cost_update and
    applies Unit Cost changes by matching on the "Item ID" column —
    never by name, so it's exact even across projects with similarly
    named items. A blank Unit Cost cell means "leave this item alone",
    which makes filling prices in over several sessions safe (you never
    have to finish the whole sheet in one sitting). Returns a summary
    dict including updated, unchanged, skipped_blank, not_found, mismatched,
    invalid, forbidden and changes (one dict per cost that would change).
    Permission is checked against each item's project at the time it is written.

    Safety: when the file carries the "Project" / "Item Name" columns (every
    file this app exports does), each row must still describe the same item
    in THIS database - a sheet exported from another data folder or an older
    restored copy reuses the same numeric ids for unrelated items, and must
    never overwrite their prices. Such rows are reported as "mismatched".
    dry_run=True computes everything without writing, for a preview."""
    import auth

    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    ws = wb.active

    header_row_idx = None
    header_values = None
    max_scan = min(6, ws.max_row or 1)
    for idx, row in enumerate(ws.iter_rows(min_row=1, max_row=max_scan, values_only=True), start=1):
        if row and str(row[0] or "").strip().lower() == "item id":
            header_row_idx = idx
            header_values = row
            break
    if header_row_idx is None:
        wb.close()
        raise ValueError(
            "Could not find the \u201cItem ID\u201d header row \u2014 is this a cost-update "
            "file exported by this app's \u201cExport Items for Cost Update\u201d?"
        )

    id_col = 0  # "Item ID" is always column A in files this app produces
    headers = [str(h or "").strip() for h in header_values]
    try:
        cost_col = headers.index("Unit Cost")
    except ValueError:
        wb.close()
        raise ValueError("Could not find the \u201cUnit Cost\u201d column in this file.")
    name_col = headers.index("Item Name") if "Item Name" in headers else None
    project_col = headers.index("Project") if "Project" in headers else None
    project_names = {}

    updated = 0
    unchanged = 0
    skipped_blank = 0
    not_found = 0
    mismatched = []
    invalid = []
    forbidden = 0
    changes = []

    wb.close()

    with db.transaction():  # all-or-nothing: a failure part-way changes no price
        for row_num, row, raw_row in _iter_value_and_formula_rows(file_path, None, header_row_idx + 1):
            raw_id = row[id_col] if id_col < len(row) else None
            if raw_id is None or str(raw_id).strip() == "":
                continue
            try:
                parsed_id = Decimal(str(raw_id).strip())
                if not parsed_id.is_finite() or parsed_id <= 0 or parsed_id != parsed_id.to_integral_value():
                    raise ValueError("Item ID must be a positive whole number")
                item_id = int(parsed_id)
                if item_id > 9223372036854775807:
                    raise ValueError("Item ID is out of range")
            except (InvalidOperation, TypeError, ValueError):
                invalid.append(f"Row {row_num}, column Item ID: invalid identifier {raw_id!r}")
                continue

            raw_cost = row[cost_col] if cost_col < len(row) else None
            if raw_cost is None and cost_col < len(raw_row) and _is_uncached_formula(raw_row[cost_col]):
                invalid.append(f"Row {row_num}, column Unit Cost: formula without a saved value "
                               f"- open the file in Excel, save it, then import again")
                continue
            if raw_cost is None or str(raw_cost).strip() == "":
                skipped_blank += 1
                continue
            try:
                cost_value = _parse_number(raw_cost)
            except ValueError as exc:
                invalid.append(f"Row {row_num}, column Unit Cost: {exc}")
                continue

            existing = db.get_item(item_id)
            if existing is None or existing["is_deleted"]:
                not_found += 1
                continue

            if existing["project_id"] not in project_names:
                project = db.get_project(existing["project_id"])
                project_names[existing["project_id"]] = project["name"] if project else ""
            project_name = project_names[existing["project_id"]]
            file_name = row[name_col] if name_col is not None and name_col < len(row) else None
            file_project = row[project_col] if project_col is not None and project_col < len(row) else None
            if ((name_col is not None and _norm_text(file_name) != _norm_text(existing["item_name"]))
                    or (project_col is not None and _norm_text(file_project) != _norm_text(project_name))):
                mismatched.append(
                    f"Row {row_num}: Item ID {item_id} is “{existing['item_name']}” "
                    f"({project_name}) here, but the file says “{file_name}” ({file_project})"
                )
                continue

            if not auth.can_edit_project(db, existing["project_id"]):
                forbidden += 1
                continue
            old_cost = existing["unit_cost"] or 0
            if abs(old_cost - cost_value) < 1e-9:
                unchanged += 1
                continue
            changes.append({"item_id": item_id, "item_name": existing["item_name"],
                            "project_name": project_name, "old": old_cost, "new": cost_value})
            if not dry_run:
                db.update_item(item_id, unit_cost=cost_value)
            updated += 1

    return {"updated": updated, "unchanged": unchanged, "skipped_blank": skipped_blank,
            "not_found": not_found, "mismatched": mismatched, "invalid": invalid,
            "forbidden": forbidden, "changes": changes, "dry_run": dry_run}

