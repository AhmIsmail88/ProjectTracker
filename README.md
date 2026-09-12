# Project Tracker v2.0

A desktop tool for tracking project materials, suppliers, purchase requests/orders,
and reference documents — with professional Excel and PDF export, and an optional
AI assistant.

## What's new in v2.31 (audit round: real bug fixes, Arabic PDFs, and a real test suite)

A full audit round — every source file re-read, business rules cross-checked
against each other, and the project's **first automated regression test suite**
added (67 tests, run with `python -m unittest discover -s tests`).

Real bugs found and fixed:

- **Multi-select Delete now deletes every selected item.** Pressing Delete
  with several rows selected deleted only the row under the cursor, even
  though the Keyboard Shortcuts reference promises "Delete selected item(s)".
  The undo snackbar now restores the whole deleted selection in one click.
- **Inline editing no longer bypasses the over-supply note rule.** Typing a
  Delivered quantity bigger than Total straight into the table saved silently
  without the required variance note (the Edit Item dialog always asked for
  one). Inline editing now prompts for the same note, and cancelling reverts
  the cell.
- **Editing an item whose supplier was (soft-)deleted no longer silently
  clears that supplier on save.** The supplier dropdown now shows the
  supplier as "(deleted)" and keeps it.
- **Restoring a project no longer resurrects items you deleted earlier on
  purpose.** Only the items deleted together with the project come back;
  items individually deleted before that stay in the Trash where you left
  them.
- **Sequence gap fixed: delete the last item, then add a new one → the "#"
  column showed 1, 2, 4.** The next-position calculation now ignores
  soft-deleted items (reproduced, then covered by a regression test).
- **Duplicate now copies On Hold / PO Issued and the over-supply note**, so a
  duplicated over-supplied item doesn't lose its required note and an On Hold
  item isn't silently un-held.
- **Backups are now crash-consistent.** Both the daily automatic backup and
  "Backup Now..." snapshot the database with SQLite's own backup API instead
  of copying the file while the app may be writing to it.
- **Search All Projects is debounced** — it scans when you pause typing,
  instead of scanning every project on literally every keystroke.
- **In-table edits no longer rebuild the entire items grid.** Only the
  affected cells of that row refresh (Remaining, Total Cost, Status colors),
  so scroll position, the current sort order and keyboard focus survive on
  projects with hundreds of rows.
- **Arabic now renders correctly in PDF reports.** The PDF engine's built-in
  font had no Arabic glyphs, so Arabic item/project names came out as
  missing boxes. When Arial or Segoe UI is present (any normal Windows
  machine), Arabic text is now shaped and rendered properly using two small
  pure-Python helpers (`arabic-reshaper`, `python-bidi`, added to
  requirements.txt). Without them the old behavior continues unchanged and a
  hint is logged once.
- **AI chat no longer breaks on `<`, `>` or `&`** in item names or replies
  (chat text is HTML-escaped now) and multi-line replies keep their line
  breaks.
- **A read-only config.json location no longer crashes the app** when saving
  preferences — it logs and keeps going.
- The title bar now shows the real version (it was still stuck at "v1.1.0").
- Smaller hardening: empty-project Excel export no longer writes an invalid
  reversed `SUM` range; purging a project no longer depends on very old
  databases having cascade foreign keys; the menu bar and status bar are
  translated in Arabic; the Attachments dialog reports upload failures
  instead of dying quietly.

Tests: `python -m unittest discover -s tests` — covers status-logic edge
cases, sequence integrity, soft delete/restore/trash, migrations (fresh +
old-shaped + idempotency), Arabic and word-order-independent search, bulk
find & replace, the Excel cost round-trip, PDF export (incl. Arabic),
automatic backups, and the config store.

## What's new in v2.30 (fixed: scrambled data in the "Possibly Forgotten" table)

Real bug found and fixed: the Dashboard's "Possibly Forgotten" table had
sorting turned on but wasn't disabling it while filling in each row's
cells \u2014 same class of bug fixed elsewhere in the app before (v2.20).
With sorting live during population, the table could re-sort itself
between placing one row's Item Name and placing that same row's
Project/Area/Days, scattering them onto the wrong rows \u2014 exactly the
"some rows show it, some don't" pattern reported. Sorting is now
disabled during population and re-enabled after, matching every other
table in the app.

A second, related bug was found and fixed alongside it: double-clicking
a row in that table to open the item used the row's on-screen position
to look up which item it was — correct only as long as the table had
never been re-sorted by clicking a column header. It now instead reads
the item's identity directly from the clicked row itself, so it opens
the right item regardless of how the table is currently sorted.

## What's new in v2.29 (professional Dashboard reports + a second status warning)

- **New warning: "Requested" quantity greater than Total quantity**
  ("over-requested") — same red/amber-family warning treatment as the
  existing over-supply and delivered-without-request warnings, in both
  the Items table and the Edit Item dialog's Computed Status chip.
- **Fixed: the delivered-without-request warning wasn't showing in the
  Edit Item dialog** — only the main items table had it; the dialog's
  own "Computed Status" preview still needed the same check wired in.
  Both spots now agree.
- **Three new "Share Reports" buttons on the Dashboard**, each exporting
  the currently checked scope (all projects, a Group, or a single
  project):
  - **"\U0001F4C4 Dashboard Summary (PDF)"** — a clean, management-ready
    report: stat cards, status pie chart + breakdown, and estimated
    value by currency. Reuses the exact same visual style already used
    by the per-project PDF report, so it looks like it belongs to the
    same family of documents.
  - **"\U0001F4C4 Possibly Forgotten (PDF)"** and **"\U0001F4CA Possibly Forgotten
    (Excel)"** — the "possibly forgotten" item list as its own separate
    document, in either format, so it can be shared on its own without
    the rest of the dashboard.

## What's new in v2.28 (two real bugs fixed from testing feedback)

- **New warning: "Delivered" with nothing ever requested.** If a
  Delivered quantity is entered while Requested quantity is still 0,
  the Status cell now shows a red "\u26A0" warning (like the existing
  over-supply warning) with a tooltip explaining why \u2014 instead of
  silently turning green as "Delivered" with no indication the item was
  never actually requested. Confirmed this was a real, reproducible gap
  in the status logic, not just a display issue.
- **Fixed: the amber "missing" highlight was unreadable in Dark Mode.**
  The Unit Cost / PR-PO warning highlight only set a background color
  and left the text color to the theme's default \u2014 in Dark Mode that
  default is light-colored text, which was nearly invisible on the
  light amber background (measured contrast ratio: 1.07, versus a
  minimum of 4.5 for readable text). Both warnings now also set an
  explicit dark, readable text color, independent of theme (measured
  contrast ratio after the fix: 8.15).

## What's new in v2.27 (Bulk Edit: Remarks + Find & Replace)

- **Bulk Edit now includes Remarks** alongside Supplier/Unit/Currency/
  Area \u2014 same checkbox-gated behavior: only checked fields change,
  and it sets the same exact text on every selected item.
- **New "\U0001F504 Find & Replace\u2026"** (grouped with Bulk Edit under one
  "\u270E Bulk Edit \u25BE" button, and also in the right-click menu): pick a
  field (Item Name, Area, Unit, or Remarks), type what to find and what
  to replace it with, and it's applied across every selected item at
  once \u2014 e.g. fixing "Puddle **Pice**" \u2192 "Puddle **Piece**" everywhere
  it was misspelled in one go. A live preview shows exactly how many of
  the selected items actually contain the text before you apply
  anything, and only those items are touched \u2014 an item that already
  has the correct spelling is left completely alone. A "Case-sensitive"
  option is available for when that distinction matters.

## What's new in v2.26 (Search All Projects: scope + word-order-independent matching)

- **"Search in:" scope** on Search All Projects: restrict to a specific
  Main Project (Group) or a single project, instead of always scanning
  every project.
- **New default match mode: "Contains all words (any order)"** — solves
  a real problem with BOQ text where the same item gets written
  differently each time (commas sometimes, word order swapped): typing
  "بادل طول الف قطر 100" now also finds a cell written as
  "بادل, قطر 100, طول الف" or "قطر 100 طوله الف مم", since it just
  checks that every word you typed is present somewhere, regardless of
  order or punctuation. Two other modes are available from the same
  dropdown: "Contains exact phrase" (the old behavior — exact wording,
  exact order) and "Exact match" (the whole field must equal what you
  typed, nothing more).
- The exported Excel file's header note now also records which scope
  and match mode were used for that search.

## What's new in v2.25 (missing PR/PO flag, Keyboard Shortcuts reference)

- **New "PR/PO" column** on the Items screen: shows "\u2713 PR, PO" when both
  are attached, or an amber "\u26A0 Missing" / "\u26A0 PR only" / "\u26A0 PO only"
  warning otherwise \u2014 no more opening Attachments on every item just
  to check. Updates immediately after you add/remove an attachment.
- **"\u26A0 Missing PR/PO only" filter checkbox**, right next to the
  existing "Missing Unit Cost only" one \u2014 isolate exactly which items
  still need documentation chased down.
- **Help \u2192 Keyboard Shortcuts**: a reference list of every shortcut in
  the app (Items screen, Projects screen, Suppliers screen, and global),
  since there are quite a few by now (Ctrl+D, Ctrl+G, Ctrl+Shift+F,
  Enter, and more).

## What's new in v2.24 (choose which column(s) Search All Projects looks in)

- **"Search All Projects" now has a checkbox per searchable column**
  (Item Name, Area, Supplier, Remarks, Unit, Status) right under the
  search box \u2014 all checked by default (searching everywhere, as
  before), but uncheck any you don't want searched to narrow results
  down instead of getting matches from every column at once. "All" /
  "None" buttons for quickly toggling them together.
- Fixes a real startup crash: opening the app after the v2.23 update
  could fail with `no such column: scope_group_id` on an existing
  database, because the new AI-chat scope index was being created
  before the migration step that adds the column. The index is now
  created after the migration, so upgrading an existing database works
  correctly.

## What's new in v2.23 (Groups become a real Main Project \u2192 sub-projects structure)

Project Groups moved from a free-text tag on each project into a proper
relationship: a Group is now its own record (with its own name), and
projects point to it — matching the real-world shape of "one Main
Project split into several section-projects."

- **Automatic, safe migration**: if you already tagged projects with a
  group name (as in v2.22), those tags are converted into real groups
  the moment you open the app — zero manual re-entry, verified against
  a copy of exactly the kind of data you had (several
  "QUBA MOSQUE EXPANSION PROJECT" sections sharing one tag).
- **Creating a project**: pick its group from a dropdown (no more
  free-typing, which risked typos creating near-duplicate groups) or
  add a new one on the spot with "\u2795 New Group\u2026". Picking a group
  that already has projects in it **pre-fills Location/Contractor/
  Currency** from the most recent one — directly aimed at the
  "Madinah" vs "MADINAH" kind of inconsistency.
- **"\U0001F4C1 Manage Groups\u2026"** on the Projects screen: rename or delete a
  group. Deleting one never touches its member projects — they just
  become ungrouped.
- **Projects screen**: a Group column plus a Group filter dropdown to
  browse just one group's projects.
- **Dashboard**: the project picker is now a proper tree — each Group
  is a checkable header with its projects nested underneath (checking
  the header checks/unchecks all of them at once), an "Ungrouped"
  bucket for anything without one, and **the panel is now resizable**
  (drag the divider) instead of stuck at a fixed cramped width — and
  remembers the size you leave it at.
- **AI Assistant**: the Scope dropdown now includes each Group (\U0001F4C1)
  alongside individual projects and "All projects" — pick a group to
  have the assistant reason over every project in it combined, with
  its own separately-saved conversation.

## What's new in v2.22 (bulk cost update, inline edit, project groups)

**1. Bulk price update via Excel round-trip** — on the Dashboard, check
one or more projects and:
- **"📤 Export for Cost Update"**: exports their items with an editable
  Unit Cost column (much faster to fill in than opening 1000+ items one
  at a time).
- **"📥 Import Cost Updates"**: reads the filled-in file back and applies
  the prices, matched by an internal Item ID (never by name, so it's
  exact). **A blank Unit Cost cell is left untouched** — fill prices in
  over as many sessions as you need; nothing gets overwritten until you
  actually type a number in that row.

**2. Inline editing** for Unit Cost / Requested Qty / Delivered Qty —
double-click a cell (or select it and press F2) to edit it directly in
the table, Excel-style, instead of opening the full Edit Item dialog.
Status, colors, and Total Cost all recompute immediately. Every other
column stays read-only via Edit Item, as before.

**3. Project Groups** — tag related section-projects (e.g. different
areas of one larger project) with the same Group name in the project
dialog, then on the Dashboard pick that group from a dropdown to check
every project in it at once, instead of clicking each one individually.
The **JSON import script now sets this automatically**: every section
file sharing the same old-tool project name is grouped together the
moment it's imported.

## What's new in v2.21 (Search All Projects now searches Remarks too)


- **Search All Projects no longer looks at the item name only** — it now
  matches against Item Name, Area, Supplier, Unit, Status, **and
  Remarks**. This covers the exact case of jotting a drawing/plate
  number in Remarks and wanting to search by it later.
- New **"Matched In"** column shows which field(s) actually matched for
  each result — hover over it to see the matching text itself (e.g. the
  plate number found in Remarks), so you can confirm the hit without
  opening the item first.

## What's new in v2.20 (auto-select + focus bug fixes)


Real bug found and fixed: after **Add Item**, the selection was being
applied *before* the table's sort step ran — and sorting a QTableWidget
can silently drop a selection made just before it, which is exactly why
the new row never ended up actually selected. Fixed by selecting *after*
the sort completes everywhere, the same reliable way Duplicate already
used.

That fix alone wasn't the whole story, though: even a correct selection
doesn't make Enter do anything unless the **table itself has keyboard
focus** — which normally only happens when you click into it with the
mouse. So on top of the ordering fix, every "select the new row" path
now also calls `setFocus()` on the table, so Enter opens it immediately:

- **Add Item** \u2192 selects & focuses the new item
- **Duplicate** \u2192 selects & focuses the new copy/copies
- **Add Project** \u2192 selects & focuses the new project
- **Add Supplier** \u2192 selects & focuses the new supplier (this screen
  didn't even attempt to auto-select before — now it matches the others)

Also fixed while auditing this: adding an item/project/supplier while a
search or status/cost filter was active could leave the new row hidden
even though it was "selected" behind the scenes. All four Add actions
now clear the active filter first, so the new row is always visible.

## What's new in v2.19 (export from Search + combined-projects export)


- **"📤 Export Results to Excel"** in Search All Projects — exports
  whatever the search currently found into one flat sheet (Project,
  Item Name, Area, Supplier, Qty, Cost, Status, Remarks columns), with
  the search term and result count noted at the top of the sheet.
- **"📤 Export Checked → One Sheet"** on the Dashboard — check one or
  more projects in the project list (the same checklist used to filter
  the Dashboard's own numbers) and export every one of their items into
  a **single combined sheet**, not one tab per project — for comparing
  several projects side by side in one view. This is different from
  "Export Filtered to Excel" on the Projects screen, which still makes
  one tab per project; this one flattens everything into one table.

## What's new in v2.18 (Dashboard: project picker + pie chart)


- **Pick which project(s) the Dashboard covers**, via a checklist on the
  left — check one, several, or leave everything unchecked for "all
  projects combined" (the previous, only, behavior). Every card, the
  chart, the currency table, and the stale-items list all update
  together based on the checked projects. "Select All" / "Clear" buttons
  included for convenience.
- **"Items by Status" is now a pie chart** (with a color-coded legend
  showing each status's count and percentage) instead of a plain table —
  drawn directly with Qt's own painter, so it adds no extra dependencies
  or install risk. Uses a distinct, higher-contrast color set chosen
  specifically for solid chart fills (reusing the pale table-chip colors
  as-is would have looked washed out on a dark background).
- Checking/unchecking a single project recomputes the numbers without
  rebuilding the whole project checklist, so it stays snappy even with
  many projects.

## What's new in v2.17 (Dashboard polish)


- Removed the unlabeled row-number column that was showing on the small
  summary tables (Status, Currency) — it served no purpose there.
- Those tables now size themselves to their actual row count instead of
  leaving a tall block of empty space below 1-2 rows.
- **"Missing Unit Cost" card now turns red when it's 100% of all items**
  (amber if it's some but not all), and shows the percentage next to the
  count — e.g. "1036 (100%)" — instead of a bare number with no context.
  "Stale Items" gets the same amber treatment when it's non-zero.
- Items with no currency set show as "(No currency set)" instead of a
  cryptic "?".
- "Possibly Forgotten" now shows a friendly "🎉 Nothing forgotten"
  message when empty, instead of a big bare empty grid that looked broken.

## What's new in v2.16 (Enter-to-open, last project, bulk edit, global search, dashboard)


- **Enter key**: on the Items table, opens Edit for the selected item; on
  the Projects table, opens the selected project. Only fires when the
  table itself has keyboard focus (not while typing in a search box).
- **The app reopens the last project you had open**, automatically, on
  startup — no more landing on the Projects list every single time. If
  that project was deleted (or you're now pointed at a different/empty
  data folder), it falls back to the Projects list safely.
- **"⚠ Missing Unit Cost only" filter** on the Items screen, plus an
  amber highlight on any Unit Cost cell that's still 0 — for quickly
  finding what pricing data hasn't been filled in yet.
- **"✎ Bulk Edit…"**: select several items (Ctrl/Shift+Click) and change
  Supplier / Unit / Currency / Area for all of them in one go. Each
  field has its own checkbox — only checked fields are touched, so nothing
  gets accidentally overwritten.
- **"🔍 Search All Projects"** (Ctrl+Shift+F): find an item by name across
  every project without opening each one — double-click (or Enter) a
  result to jump straight to that project with the item selected.
- **New "Dashboard" tab**: active project/item counts, items broken down
  by status, estimated value per currency, a missing-unit-cost count,
  and a "Possibly Forgotten" list of items still "Not requested" after
  14+ days of no activity — double-click one to jump straight to it.

Not included this round: freezing the first column while scrolling
horizontally through a wide table. It needs a synced overlay widget
(QTableWidget doesn't support it natively) which is real UI-rendering
complexity that couldn't be verified without a live Qt display — rather
than ship that partially-tested, it's deferred; ask any time to pick it
back up.

## What's new in v2.15 (automatic backups)

- **Automatic daily backup of the database** — happens silently on
  startup, at most once a day (opening the app several times in one day
  won't create duplicates), keeping the most recent 14 days. Lives in a
  `backups/` folder next to your data. Never blocks the app from opening
  if it fails (e.g. disk full) — it just quietly tries again next time.
  Only the database itself (fast, always small); attachments aren't
  included in the automatic backup since copying them every startup
  would slow things down for little benefit — that's what the full
  manual backup below is for.
- **Status bar now shows the last backup time** next to the data folder,
  so you can see at a glance that it's actually happening.
- **File \u2192 "Backup Now..."** (a full backup including every
  attachment file, zipped) now runs in the background instead of
  freezing the window — useful once a project has accumulated a lot of
  PR/PO/warranty documents. Verified the resulting zip actually contains
  a fully restorable database plus every attachment file, not just that
  the zip gets created.

## What's new in v2.14 (row auto-fit fix, multi-project export, column layout memory)

- **Row height now shrinks back automatically**, not just grows — before,
  a row that grew tall to fit wrapped text in a narrow column stayed
  tall forever even after you widened that column back out. Any column
  resize now re-fits every row's height to its actual content.
- **"📤 Export Filtered to Excel" on the Projects screen**: search/filter
  the project list, click it, and every project currently shown exports
  into **one Excel file, one tab per project** — instead of exporting
  projects one at a time. Runs in the background like the other exports.
- **Status column moved back to the end** of the Items table (its
  original spot) — not needed front-and-center right now.
- **Column order and widths are now remembered per table** — drag a
  column to reorder it, resize it, and that arrangement is what you'll
  see next time you open the app, automatically, no "save as default"
  step. Right-click → "Reset Columns to Default" undoes this if you want
  to start over.

## What's new in v2.13 (layout cleanup, based on real screen review)

- **Status column moved right after "#"** — it used to be the very last
  column, meaning you had to scroll all the way right in a wide table
  just to see it, even though it's the core info this app tracks.
- **Row/item number ("#") no longer shows decimals** ("1" instead of
  "1.00") — it was being formatted like every other numeric column.
- **Repeated "Pump Station / Area" text is now dimmed** when it's
  identical to the row directly above it — with hundreds of items
  grouped by area, reading the same text over and over added noise
  without adding information. The underlying text is unchanged (search
  and the Area filter both still work exactly as before).
- **Move Up / Down / Top / Bottom / Move to Position** are now one
  "↕ Move" dropdown button instead of 5 separate toolbar buttons — same
  actions, same keyboard shortcuts, a cleaner toolbar.
- "Total cost: 0.00" on a fully-populated project is expected, not a
  bug, if Unit Cost hasn't been filled in for those items yet — it's a
  live sum of Total Qty × Unit Cost across whatever's currently visible.

## What's new in v2.12 (fixing the "350-row move" problem)

- **Duplicate now inserts the copy right next to the original** instead
  of appending it at the very end of the list — this was the #1 cause of
  needing a long manual move in the first place, so most of the time
  you'll no longer need to move anything after duplicating at all. Works
  correctly for multi-select duplicates too (each copy lands next to its
  own original, keeping everyone's relative order).
- **"⇈ Top" / "⇊ Bottom" buttons** (+ **Ctrl+Alt+↑/↓**): jump the
  selected item(s) straight to the very top or bottom of the list in one
  click, regardless of list length.
- **"🎯 Move to…" button** (+ **Ctrl+G**): type a target row number and
  the selection jumps straight there — no more stepping through every
  row in between one at a time.
- All three work with single or multi-selection, are available from the
  toolbar, the right-click menu, and keyboard shortcuts, and — like
  every reorder in this app — keep the sequence gap-free automatically.
- Verified with a 350-item simulation matching the exact scenario
  described: duplicating the last item, moving an item straight to the
  top, and jumping an item to an arbitrary position — all complete
  instantly regardless of list size.

## What's new in v2.11 (Import from Excel)

- **New "📥 Import from Excel" button** on the Projects screen — brings an
  existing spreadsheet-based tracker into the app instead of retyping
  everything by hand.
  - Choose at import time: create a brand-new project from the file, or
    add the rows into a project that already exists.
  - **Column mapping, not a fixed format**: your spreadsheet's columns
    are matched to our fields (Item Name, Area, Supplier, Unit, Qty,
    Unit Cost, etc.) with a best-effort auto-guess you review and can
    freely override — nothing is assumed silently.
  - Header-row detection tolerates a title row above the real headers
    (common in hand-built BOQ sheets).
  - **Suppliers are matched by name (case-insensitive), never
    auto-created** — an unmatched supplier name is reported at the end
    and the item is imported with no supplier assigned, so imports never
    create a pile of near-duplicate supplier records from
    typos/inconsistent spelling in an old spreadsheet.
  - A live preview of the mapped rows is shown before anything is
    imported; blank rows and rows with no item name are skipped and
    reported, not silently dropped or guessed at.
  - Runs in the background so the window doesn't freeze on a large file.
- **JSON import** (from an older tool's export format) was intentionally
  **not** built into the app — it's a one-off, rare need, so it'll be a
  small standalone script written once an actual sample file is
  available, rather than permanent UI/maintenance surface for something
  used once in a while.

## What's new in v2.10 (visible .env diagnostics)

- **"Test AI Connection" now shows exactly which `.env` path it looked for,
  and whether it actually found a file there** — right in the chat log,
  every time you run the test. This turns "why is it still using the
  wrong model?" from a guessing game into an immediate, visible fact.
- The single most common real-world cause of ".env changes aren't taking
  effect": the file isn't actually named `.env` where the app expects it —
  most often because Windows silently saves it as `.env.txt` when "hide
  known file extensions" is on (the default). The connection test now
  calls this out explicitly when it happens, with the exact command to
  check (`dir .env*` in Command Prompt).

## What's new in v2.9 (packaging + AI config reliability fixes)

- **Fixed: `.env` / `config.json` / database location would break once
  packaged as a `.exe`.** PyInstaller's `--onefile` mode runs the actual
  code from a temporary folder at runtime — every place that used to
  compute "the app's folder" from `__file__` (config.py, database.py,
  ai/openrouter_client.py, main.py) would have silently pointed at that
  vanishing temp folder instead of the real folder holding the `.exe`.
  In practice this would have meant: `.env` never found (AI always
  "not configured"), and worse, `config.json` (which remembers your
  chosen data folder) forgetting itself on every single run. Fixed via a
  new shared `app_paths.py` that correctly resolves to the `.exe`'s real
  folder in a packaged build (via `sys.frozen`/`sys.executable`) and to
  the source folder in normal `python main.py` use. Verified with a
  simulated frozen-mode test.
- **Fixed: editing `OPENROUTER_MODEL` (or the API key) in `.env` could be
  silently ignored.** Two causes: `load_dotenv()` doesn't overwrite a
  variable that's already set in the process environment unless told to
  (now calls it with `override=True`), and the app only read `.env` once
  per run and cached it forever (now re-reads the small file on every AI
  call instead, so an edit takes effect on your very next message — no
  restart needed). Reproduced the exact symptom (a stale model showing
  up instead of the one just set in `.env`) and confirmed both fixes
  resolve it.

## What's new in v2.8

- **Filter by Area / Pump Station**: a 4th filter dropdown next to
  search/status/supplier on the Items tab, populated automatically from
  whatever area values actually exist on the project's items.
- **Multi-select Duplicate**: select several items (Ctrl/Shift+Click) and
  Duplicate (button, right-click menu, or Ctrl+D) copies all of them at
  once instead of just one.
- **Multi-select Move Up/Down**: select several items and Move Up/Down
  (button, Alt+↑/↓) moves the whole group together in one step — each
  selected item shifts past its nearest non-selected neighbor, so the
  group stays together and keeps its relative order, the same way
  reordering multiple selected tracks in a playlist works. Works for both
  contiguous and non-contiguous selections.
- **Rows now auto-fit their text height automatically** after every
  load/filter/edit — long item names or remarks are fully visible without
  having to double-click each row's border one at a time (the manual
  double-click-to-fit from v2.4 is still there too, for fine-tuning after
  a manual edit).
- Keyboard shortcuts for Edit (**Ctrl+E**) and Duplicate (**Ctrl+D**) were
  already in place — now documented via tooltips on the buttons
  themselves, along with a hint that Duplicate/Move work on whatever's
  currently selected (one item or many).

## What's new in v2.7 (UI polish pass)

Implemented the simplified 7-point UI plan (icon system, slide-in drawers,
and blur effects were intentionally skipped — see project notes on why):

1. **Toolbar buttons grouped with separators** in the Items tab: Edit
   group (Add/Edit/Duplicate/Delete) | Order group (Move Up/Down) |
   Attachments group (Attachments/History) — instead of one long row.
2. **Table hover + selection highlight**, plus a **"Showing X of Y"**
   status line with a **"✕ Clear Filters"** button that only appears when
   a search/status/supplier filter is actually active.
3. **Nav bar redesigned as tabs**: the active page (Projects/Suppliers/AI)
   now shows a colored underline instead of a filled background block,
   matching the look of the tabs already used elsewhere in the app.
4. **Removed the "Are you sure?" confirmation for normal deletes**
   (items, projects, suppliers) — every one of these is already a soft
   delete with an Undo button, so a confirmation dialog was just an extra
   click for no real safety benefit. Confirmations are kept only for
   genuinely irreversible actions ("Delete Forever" in the Trash screens).
5. **Export buttons now run in the background** with a "⏳ Exporting…"
   state instead of freezing the window — matters most for larger
   projects or PDF reports with many attachments.
6. **Built-in Qt icons** (no external icon font/files, so nothing to
   package or that can go missing in a PyInstaller build) added to the
   clearest cases: Delete (trash icon), Move Up/Down (arrows).
7. **"Inter" added as the preferred font** ahead of Segoe UI/Cairo, with
   automatic fallback if it isn't installed on the machine — no download
   or packaging required.

Skipped for now (see rationale in project discussion): a full custom icon
font system, slide-in drawer panels replacing dialogs, and background
blur effects — these would be a real architectural change with real risk
to a lot of already-working screens, for a desktop internal tool where
the payoff doesn't clearly justify it.

## What's new in v2.6 (removed AI grouping, simplified)

- **Removed "Smart Grouped Export (AI)"** entirely — after real-world
  testing, free-tier AI models were too unreliable for this specific task
  (several return no content at all when they're "reasoning" models that
  burn their whole token budget thinking before answering — not something
  more prompt engineering can fix). Rather than keep patching an
  unreliable feature, it's gone.
- **Replaced with "Export Filtered View to Excel"** — a plain,
  deterministic alternative with no AI involved: use the existing
  search box / status filter / supplier filter on the Items tab to narrow
  the list down to whatever you want (e.g. only pumps, only a specific
  status), then export exactly what's visible with one click. Same
  professional formatting as the full report.
- **"Test AI Connection" button** (AI Assistant screen) — sends one quick
  test message and reports back clearly (model name, latency, reply, or
  the exact error) so you can verify your `.env` setup works in a couple
  of seconds, instead of only finding out mid-way through something
  bigger. The general AI chat and quick-report features are unaffected by
  the grouping removal and still work as before.
- If you do want to keep experimenting with AI features later: the
  `.env.example` default model was updated to
  `meta-llama/llama-3.3-70b-instruct:free` — a plain instruct model (not
  a "reasoning" model), which answers directly instead of spending its
  budget thinking first. OpenRouter's free model list changes weekly
  though, so if a model stops working, check
  https://openrouter.ai/models?max_price=0 for a current non-reasoning
  alternative.

## What's new in v2.5

- **Fixed the two exact errors from real usage**: `'NoneType' object has no
  attribute 'strip'` and `Expecting ',' delimiter...` were both caused by
  asking the AI to output JSON — free-tier models are noticeably better at
  plain text than strict JSON, and a single missing comma corrupted an
  entire batch. The AI now outputs one simple `id|sheet|subgroup` line per
  item instead of JSON: a malformed line only costs that one item, not the
  whole batch, and a failed request now retries once automatically before
  falling back to Uncategorized.
- **"AI is thinking…" indicator**: sending a chat message (or generating a
  quick report) now shows a visible, animated status under the chat log
  and disables the input box until the reply (or an error) arrives, so
  it's never unclear whether it's still working.
- **Removed the sidebar** — replaced with a single compact top bar
  (Projects / Suppliers / AI Assistant on the left, theme/language on the
  right), reclaiming the tall, mostly-empty column on the left.
- **Merged the Tracker screen's header** (back button + project title +
  breadcrumb) from three stacked rows into one, cutting the wasted space
  at the top of the screen.

## What's new in v2.4

- **Fixed: existing sequence gaps now auto-repair on startup.** The v2.3.1
  fix only stopped *new* gaps from forming — it didn't touch gaps that
  already existed in your database from before that fix. Opening the app
  now also retroactively closes any existing gaps automatically (safe,
  cheap, runs every startup, no button to press).
- **AI classification, triggered from the chat itself**: in the AI
  Assistant screen, type your grouping request in the normal chat box
  (e.g. *"group pumps together, group pipes by material"*) and click the
  new **"📊 Grouped Excel Export"** button next to Send — it opens the
  review screen with your request pre-filled and classification already
  running, instead of having to open a separate dialog and retype it.
  The review-before-export safety step is unchanged.
- **Excel-style column/row auto-fit**: double-click the edge of a column
  header (or row header) to auto-fit it to its content — exactly like
  Excel. Select several columns or rows first and double-click one edge
  to auto-fit all of them together in one go.
- **Denser, tighter layout**: reduced page margins, button/tab/header
  padding, sidebar width, and default row height across every screen to
  cut down on wasted space.

## Bug fixes in v2.3.1

- **Fixed: the "#" sequence left gaps after deleting an item.** Deleting an
  item only marked it hidden but never renumbered the items after it, so
  the visible order could jump (e.g. "39, 42, 43…" after items 40–41 were
  deleted). Deleting now renumbers the remaining items as a clean 1..N
  sequence immediately; restoring a deleted item places it at the end of
  the current sequence instead of reusing its old (possibly now-colliding)
  number.
- **Fixed: Smart Grouped Export was unreliable on larger item lists.**
  Two causes: (1) the OpenRouter request never set `max_tokens`, so
  free-tier models silently truncated long classification replies (a
  40+ item project needs a fairly long JSON reply) — output is now
  requested with an explicit, generous token budget; (2) classification
  is now done in small batches (15 items per AI request by default)
  instead of one big request, which is both more reliable and shows
  live progress ("Classifying items... 15/45"). Sheet names stay
  consistent across batches — each batch is told which sheet names were
  already used earlier in the same run, so it reuses "Pumps" instead of
  inventing a near-duplicate like "Submersible Pumps".

## What's new in v2.3

- **Smart Grouped Export (AI)**: in a project's Reports tab, describe how
  you want items grouped (e.g. *"group pumps together, group pipes and
  fittings by material"*) and the AI proposes which Excel **sheet** each
  item belongs to (it invents sheet names based on what's actually in
  your project — "Pumps", "Pipes & Fittings", etc.) and an optional
  **sub-group** within that sheet (e.g. same capacity or material) that's
  rendered as one merged cell spanning those rows.
  - Items the AI can't confidently classify land on their own
    **"Uncategorized"** sheet instead of being guessed.
  - **Nothing is exported until you review it**: a table shows every
    item's proposed sheet/sub-group, and you can edit any cell before
    clicking Export.
  - **Safety by design**: the AI only ever returns a small classification
    list — it never touches the file system or writes the Excel file
    itself. Every item id in its reply is checked against the project's
    real items; anything hallucinated is discarded, and anything missing
    falls back to "Uncategorized" automatically. If the AI reply can't be
    parsed at all (rare, but free-tier models aren't perfect), every item
    safely falls back to "Uncategorized" and you can still finish the
    grouping by hand — it never blocks or crashes.

## What's new in v2.2

- **Post-delivery / handover document categories**: attachments now support
  7 new categories beyond the original PR/PO/Reference — **Warranty, O&M
  Manual, Test Certificate, As-Built Drawing, Spare Parts List, MIR
  (Material Inspection Report), and Invoice**.
- **Confirmation before uploading post-delivery docs on a non-delivered
  item**: if you try to attach one of these 7 categories to an item whose
  status isn't yet "Delivered", the app asks you to confirm first (in
  case the status isn't updated yet) rather than blocking you outright.
- **Both reports now show these documents**:
  - **Excel**: two grouped header sections — "Procurement Documents"
    (PR/PO/Reference) and "Post-Delivery / Handover Documents" (the 7 new
    categories) — each with its own clickable column, same as before.
  - **PDF**: a compact "Post-Del. Docs" column (e.g. "2/7") shows at a
    glance how many of the 7 categories are on file for each item, plus a
    "Post-Delivery Documents Summary" section at the end listing exactly
    which documents are present/missing per item.
- **Bug fix**: category names containing `&` (like "O&M Manual") were
  being corrupted in the PDF report due to unescaped special characters;
  all dynamic text in the PDF (item names, notes, project info, category
  names) is now properly escaped.

## What's new in v2.1

- **"Partially Requested" status**: if the requested quantity is more than
  zero but less than the item's total quantity, the status is now
  **Partially Requested** instead of jumping straight to "Requested" — so
  you can tell at a glance whether you've only requested part of the BOQ
  quantity for an item.
- **Audit log (change history)**: every create/update/delete/restore on a
  project, item, or supplier is now recorded locally — field changed, old
  value, new value, and timestamp. This is stored in the same
  `project_tracker.db` file (table `audit_log`), so it needs no separate
  setup and doesn't slow the app down (SQLite handles this scale easily).
- **Visual Timeline / History**:
  - Each project's Tracker screen has a new **"Activity Log"** tab showing
    everything that happened on that project (item and project changes).
  - A **"History"** button is available for a single item (Items toolbar +
    right-click menu), a single supplier (Suppliers screen), and a single
    project (Projects screen) — opens a focused timeline for just that
    record.
- **Persistent AI memory**: the AI Assistant's conversations are now saved
  locally per scope (a specific project, or "All projects") in the
  `ai_chat_history` table, and reloaded automatically next time you open
  the app or switch scope. A **"New Conversation"** button clears the
  saved conversation for the current scope if you want a fresh start.
- **The AI now sees recent activity, not just current state**: each
  request includes a short summary of the most recent changes (up to ~40
  entries) for the selected scope, so you can ask things like *"what
  changed on this project this week?"*. Only a bounded, recent slice is
  ever sent — not the entire history — to keep answers fast and within
  the model's context limits.

## What's new in v2.0

- **Projects is now its own screen.** Open a project to go into a dedicated
  Tracker workspace (Items + Reports tabs) for that project; "\u2190 Back to Projects"
  returns you to the list. Search filters by **project name or number**.
- **Suppliers** and the **AI Assistant** are now their own screens too, reachable
  from the left sidebar (suppliers are shared across all projects, so they no
  longer live inside a single project's tabs).
- **Status is calculated automatically** from quantities — you no longer pick it
  manually. Rules (see `constants.compute_status`):
  1. "On Hold" checkbox always wins (manual override).
  2. Delivered ≥ Total → **Delivered**.
  3. Some delivered, not all → **Partially Delivered**.
  4. "PO Issued" checkbox ticked, nothing delivered yet → **PO Issued**.
  5. Something requested, no PO yet → **Requested**.
  6. Otherwise → **Not requested**.
- **Remaining quantities are computed automatically** and shown both in the item
  form and as table columns: *Remaining to Request* (Total − Requested) and
  *Remaining to Deliver* (Total − Delivered).
- **Over-supply validation**: if Delivered > Total, the app requires a short note
  before saving, and highlights that row in a distinct purple/lilac color (with a
  "⚠" marker) in the table, Excel export, and PDF export.
- **Currency per item**: adding/editing an item now has a currency dropdown
  (defaults to the project's currency, but can be overridden per item).
- **Add Supplier without leaving the Item form**: a "+ Suppliers" button next to
  the supplier dropdown opens the same Add Supplier dialog and selects the new
  supplier immediately.
- **Clean manual ordering**: use "Move Up" / "Move Down" (or Alt+↑ / Alt+↓, or the
  right-click menu) to reorder items — the sequence is renumbered as a clean
  1..N every time, so you never end up with "1, 2, 3, 5, 4".
- **Undo for every delete.** Deleting a project, item, or supplier is a *soft*
  delete: a snackbar appears at the bottom with an "Undo" button (~7 seconds).
  Soft-deleted projects/items can also be recovered later from the **Trash**
  buttons (Projects screen, and inside a project's Tracker screen for its items).
- **More professional look**: refreshed dark/light color palettes (indigo/slate
  with a teal accent), status colors re-tuned for readability, a proper sidebar
  navigation layout.
- **Arabic support**: a "Language" button in the toolbar toggles the whole UI
  between English and Arabic (with right-to-left layout). Preference is
  remembered between runs.
- **Fixed PDF export text overflow**: every cell in the PDF item table (not just
  the item name) is now wrapped properly, so long item/supplier/area names wrap
  within their own cell instead of being clipped or bleeding into the next
  column. Status cells are colored the same way as the on-screen table.
- **AI Assistant screen** (optional, off by default): ask questions like *"what's
  still pending on Site A?"* in Arabic or English. It uses **OpenRouter**
  (openrouter.ai) instead of a paid API directly, so you can run it for free
  using OpenRouter's free-tier models. See "AI Assistant setup" below.

## 1. Install Python (one-time setup)

Download Python 3.11+ from https://www.python.org/downloads/windows/
**Important:** during install, check the box **"Add python.exe to PATH"**.

## 2. Install the required libraries

Open Command Prompt in this folder and run:

```
pip install -r requirements.txt
```

## 3. (Optional) AI Assistant setup

The AI Assistant screen works without any setup — it just shows a reminder to
configure it. To enable it:

1. Copy `.env.example` to `.env` (same folder as `main.py`).
2. Create a free account at https://openrouter.ai and generate an API key at
   https://openrouter.ai/keys.
3. Put the key in `.env` as `OPENROUTER_API_KEY=...`.
4. Optionally pick a different free model in `OPENROUTER_MODEL` (browse
   free-tier models at https://openrouter.ai/models?max_price=0).

The `.env` file is never bundled into the app or sent anywhere except to
OpenRouter's API, and it's ignored by git-style tooling by convention — keep it
private since it holds your API key.

## 4. Run the app

```
python main.py
```

**First run:** the app will ask you to choose a folder where it should keep
its data — pick any folder you like (a local folder, or a shared network
folder). It remembers your choice in `config.json` next to `main.py`.

That chosen folder will contain:
- `project_tracker.db` — all your projects, items, suppliers
- `attachments/` — every PR/PO/reference file you upload

**To move your data later:** use **File → Change Data Folder...** inside the
app. It offers to copy your existing data into the new folder automatically.

**To find your data folder any time:** use **File → Open Data Folder**, or
check the status bar at the bottom of the window.

**To back up:** use **File → Backup Now...** — creates a single dated `.zip`
with your database and all attachments, ready to copy to a USB drive or
shared folder.

**Existing databases** created with v1.x open normally — the app adds any new
columns it needs automatically the first time it opens an older `project_tracker.db`
(see `Database._migrate_schema`), so no manual migration step is required.

## 5. Package it as a standalone .exe (so non-programmers can just double-click it)

```
pyinstaller --noconfirm --onefile --windowed --name "ProjectTracker" main.py
```

The finished file appears in the `dist/` folder as `ProjectTracker.exe`. If you
use the AI Assistant, remember to also copy your `.env` file next to the `.exe`.

> Note: with everyone running their own local copy of the .exe and their own
> `project_tracker.db`, each person's data stays separate. If several people
> need to see and edit the *same* live data at the same time, keep in mind
> SQLite is not designed for concurrent writers over a network share — for
> genuinely simultaneous multi-user editing you'd want to move to a real
> client/server database (see roadmap below).

## Project structure

```
project_tracker/
├── main.py                   # App entry point / main window / navigation
├── config.py                  # Remembers which folder holds the data
├── constants.py                # Statuses, colors, currencies, status-calc logic
├── i18n.py                     # English/Arabic string table
├── database.py                 # SQLite data layer (soft-delete, auto status, ordering)
├── ui/
│   ├── styles.py                # Dark & Light QSS themes
│   ├── widgets.py                # Undo snackbar
│   ├── table_utils.py            # Shared QTableWidget helpers
│   ├── dialogs.py                 # Add/Edit popups (project, item, supplier, attachments)
│   ├── projects_page.py            # Projects screen + Trash
│   ├── items_page.py               # Tracker screen (items + reports) for one project
│   ├── suppliers_page.py            # Suppliers screen
│   └── ai_page.py                    # AI Assistant screen
├── ai/
│   └── openrouter_client.py           # OpenRouter API client
├── export/
│   ├── excel_export.py                 # Professional .xlsx report generator
│   └── pdf_export.py                    # PDF report generator (summary + pie chart + table)
├── attachments/                          # Uploaded PR/PO/reference files land here automatically
├── project_tracker.db                     # Created automatically on first run
├── .env.example                            # Copy to .env for the AI Assistant
└── requirements.txt
```

## Known simplifications / what's next

- Trash currently keeps soft-deleted records indefinitely until you use
  "Delete Forever" or an admin runs `Database.empty_trash()`; there's no
  automatic purge scheduler yet.
- Language switching rebuilds the whole screen (simplest reliable approach for
  a project this size) rather than patching every widget in place — you may
  notice a brief flicker when toggling.
- **Multi-user network mode**: once there's a Windows Server able to host a
  Python service, this same data layer can be swapped to a real client/server
  database with minimal changes to the rest of the app.
- **User accounts / roles** (Admin, PM, Viewer) — not built yet.
