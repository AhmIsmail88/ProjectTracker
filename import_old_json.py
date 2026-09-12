"""
scripts/import_old_json.py

ONE-OFF helper — NOT part of the packaged app / .exe. Run this once with
Python to bring project files exported from the old tool (the
"QUBA MOSQUE...json" format) into Project Tracker's real database, then
delete/ignore this script. It's not wired into the UI on purpose: this
kind of import happens rarely, so it isn't worth permanent screen space
or maintenance.

WHAT IT DOES
    - Connects to the SAME database the app itself uses (reads the data
      folder from config.json, exactly like main.py does) — imported
      items show up in the app immediately, no extra step.
    - Creates ONE NEW project per JSON file you give it, named after the
      file itself (e.g. "QUBA MOSQUE EXPANSION PROJECT_South irrigation
      tank.json" -> project "QUBA MOSQUE EXPANSION PROJECT_South
      irrigation tank") — matching how projects in this app are already
      named per section. If you'd rather MERGE several JSON files into
      one project instead, don't run this as-is — ask for a tweak first.
    - Project location / contractor / project number / currency come
      from the JSON's own top-level fields.
    - Each item's supplier is matched by name (case-insensitive) against
      suppliers that already exist in the app. A name that doesn't match
      anything is left unassigned on that item — never auto-created —
      same rule used by the Excel importer, so old typos/inconsistent
      spelling don't create messy duplicate supplier records.
    - Status is NOT copied from the old file — this app always computes
      status itself from the quantities (and it has more statuses, e.g.
      "Partially Requested", than the old tool did), so it's recomputed
      fresh on import.
    - pr_path / po_path from the old tool are FILE PATHS on the old
      machine, not files this script has access to, so they are not
      imported as attachments — the script instead reports which items
      had one of these set, so you know which ones to manually attach
      again through the app's Attachments screen if you want them.
    - Skips a JSON file entirely (with a clear message) if a project
      with that exact name already exists, so re-running this by
      accident never creates duplicate projects/items.

USAGE
    From the project_tracker folder (same place as main.py):

        python scripts/import_old_json.py "path/to/file1.json" "path/to/file2.json"

    or point it at a whole folder of .json files:

        python scripts/import_old_json.py "path/to/old_exports_folder"

    A summary is printed at the end for every file processed.
"""

import json
import os
import sys

def _find_app_dir():
    """Locates the project_tracker folder (the one with config.py/main.py
    in it) regardless of whether this script was placed directly inside
    project_tracker/ or in a project_tracker/scripts/ subfolder — both
    are common, and guessing wrong here would silently point at the
    wrong config.json / database."""
    here = os.path.dirname(os.path.abspath(__file__))
    for candidate in (here, os.path.dirname(here)):
        if os.path.isfile(os.path.join(candidate, "config.py")):
            return candidate
    print(f"! Could not find config.py next to this script or one folder up "
          f"(looked in: {here} and {os.path.dirname(here)}).\n"
          f"  Make sure import_old_json.py sits inside your project_tracker folder\n"
          f"  (the same one that has main.py, database.py, config.py in it).")
    sys.exit(1)


sys.path.insert(0, _find_app_dir())

import config
from database import Database


def _collect_json_paths(args):
    paths = []
    for arg in args:
        if os.path.isdir(arg):
            for name in sorted(os.listdir(arg)):
                if name.lower().endswith(".json"):
                    paths.append(os.path.join(arg, name))
        elif os.path.isfile(arg) and arg.lower().endswith(".json"):
            paths.append(arg)
        else:
            print(f"  ! Skipping (not a .json file or folder): {arg}")
    return paths


def _project_already_exists(db, name):
    return any(p["name"] == name for p in db.get_projects())


def import_one_file(db, json_path):
    project_name = os.path.splitext(os.path.basename(json_path))[0]
    print(f"\n=== {os.path.basename(json_path)} ===")

    if _project_already_exists(db, project_name):
        print(f"  ! A project named {project_name!r} already exists — skipping this file "
              f"so nothing gets duplicated. Rename/delete that project first if you really "
              f"want to re-import it.")
        return

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    project_id = db.add_project(
        name=project_name,
        location=data.get("location", "") or "",
        contractor=data.get("contractor", "") or "",
        project_number=data.get("project_number", "") or "",
        currency=data.get("currency", "SAR") or "SAR",
    )

    suppliers_by_name = {s["name"].strip().lower(): s["id"] for s in db.get_suppliers()}

    imported = 0
    skipped = []
    unmatched_suppliers = set()
    had_old_attachments = []

    for item in data.get("items", []):
        item_name = (item.get("item_name") or "").strip()
        if not item_name:
            skipped.append(f"item id {item.get('id', '?')}: no item name")
            continue

        supplier_id = None
        supplier_raw = (item.get("supplier") or "").strip()
        if supplier_raw:
            key = supplier_raw.lower()
            if key in suppliers_by_name:
                supplier_id = suppliers_by_name[key]
            else:
                unmatched_suppliers.add(supplier_raw)

        db.add_item(
            project_id,
            item_name=item_name,
            pump_station=(item.get("pump_station") or "").strip(),
            supplier_id=supplier_id,
            unit=(item.get("unit") or "").strip(),
            currency=data.get("currency", "SAR") or "SAR",
            total_quantity=float(item.get("total_quantity") or 0),
            requested_quantity=float(item.get("requested_quantity") or 0),
            delivered_quantity=float(item.get("delivered_quantity") or 0),
            unit_cost=float(item.get("unit_cost") or 0),
            remarks=(item.get("remarks") or "").strip(),
        )
        imported += 1

        if (item.get("pr_path") or "").strip() or (item.get("po_path") or "").strip():
            had_old_attachments.append(item_name)

    print(f"  Project created: {project_name!r} (id={project_id})")
    print(f"  Imported {imported} item(s).")
    if skipped:
        print(f"  Skipped {len(skipped)}: {skipped[0]}{' ...' if len(skipped) > 1 else ''}")
    if unmatched_suppliers:
        print(f"  Supplier(s) not matched (left unassigned): {', '.join(sorted(unmatched_suppliers))}")
    if had_old_attachments:
        print(f"  {len(had_old_attachments)} item(s) had a PR/PO file in the old tool "
              f"(not carried over — re-attach manually if needed):")
        for name in had_old_attachments[:10]:
            print(f"    - {name}")
        if len(had_old_attachments) > 10:
            print(f"    ... and {len(had_old_attachments) - 10} more")


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/import_old_json.py <file1.json> [file2.json ...] | <folder>")
        sys.exit(1)

    data_dir = config.load_data_dir()
    if not data_dir:
        print("Could not find the app's data folder (no config.json / data folder set yet).\n"
              "Open the app once and set a data folder first, then re-run this script.")
        sys.exit(1)

    db_path = config.db_path_for(data_dir)
    attachments_dir = config.attachments_dir_for(data_dir)
    print(f"Using database: {db_path}")
    db = Database(db_path, attachments_dir)

    json_paths = _collect_json_paths(sys.argv[1:])
    if not json_paths:
        print("No .json files found in the given path(s).")
        sys.exit(1)

    for path in json_paths:
        try:
            import_one_file(db, path)
        except Exception as exc:  # noqa: broad-except — keep going with the rest of the batch
            print(f"  ! Failed to import {path}: {exc}")

    print("\nDone. Open the app to see the imported project(s).")


if __name__ == "__main__":
    main()
