# -*- coding: utf-8 -*-
"""Database layer: CRUD, sequence integrity, soft delete/restore, purge,
duplicate flags, migrations (fresh/twice/old-shaped), search (incl.
Arabic + word-order-independent), bulk find & replace, chat history,
dashboard summary."""
import os
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import Database


def make_db():
    tmp = tempfile.mkdtemp(prefix="pt_test_")
    db_path = os.path.join(tmp, "project_tracker.db")
    att_dir = os.path.join(tmp, "attachments")
    return Database(db_path, att_dir), tmp


class TestItemsAndSequencing(unittest.TestCase):
    def setUp(self):
        self.db, self.tmp = make_db()
        self.pid = self.db.add_project("Seq Project")

    def test_add_and_get_item(self):
        iid = self.db.add_item(self.pid, item_name="Pump", total_quantity=5)
        it = self.db.get_item(iid)
        self.assertEqual(it["item_name"], "Pump")
        self.assertEqual(it["sort_order"], 1)
        self.assertEqual(it["status"], "Not requested")

    def test_delete_compacts_sequence_without_gaps(self):
        ids = [self.db.add_item(self.pid, item_name=n) for n in "ABCDE"]
        self.db.delete_item(ids[1])  # B
        items = self.db.get_items(self.pid)
        self.assertEqual([i["item_name"] for i in items], ["A", "C", "D", "E"])
        self.assertEqual([i["sort_order"] for i in items], [1, 2, 3, 4])

    def test_add_after_delete_leaves_no_gap(self):
        ids = [self.db.add_item(self.pid, item_name=n) for n in "ABC"]
        self.db.delete_item(ids[2])  # delete the LAST item
        self.db.add_item(self.pid, item_name="D")
        self.assertEqual(
            [i["sort_order"] for i in self.db.get_items(self.pid)],
            [1, 2, 3],
            "adding after a delete must not leave a visible sequence gap",
        )
        # same for restoring from trash: appends after the active sequence
        self.db.restore_item(ids[2])
        self.assertEqual(
            [i["sort_order"] for i in self.db.get_items(self.pid)],
            [1, 2, 3, 4],
        )

    def test_restore_puts_item_at_end(self):
        ids = [self.db.add_item(self.pid, item_name=n) for n in "ABCDE"]
        self.db.delete_item(ids[1])
        self.db.restore_item(ids[1])
        items = self.db.get_items(self.pid)
        self.assertEqual([i["item_name"] for i in items], ["A", "C", "D", "E", "B"])
        self.assertEqual(items[-1]["sort_order"], 5)

    def test_move_single(self):
        ids = [self.db.add_item(self.pid, item_name=n) for n in "ABCDE"]
        self.db.move_item(self.pid, ids[3], -1)  # D up
        self.assertEqual(
            [i["item_name"] for i in self.db.get_items(self.pid)],
            ["A", "B", "D", "C", "E"],
        )

    def test_move_group_keeps_relative_order(self):
        ids = [self.db.add_item(self.pid, item_name=n) for n in "ABCDE"]
        # Playlist-style: each selected item swaps past its nearest
        # non-selected neighbour; the selection keeps its relative order.
        self.db.move_items_group(self.pid, [ids[0], ids[3]], 1)  # A and D down
        self.assertEqual(
            [i["item_name"] for i in self.db.get_items(self.pid)],
            ["B", "A", "C", "E", "D"],
        )
        # A contiguous block really does move as one unit.
        self.db.move_items_group(self.pid, [ids[0], ids[3]], -1)  # A and D up
        self.assertEqual(
            [i["item_name"] for i in self.db.get_items(self.pid)],
            ["A", "B", "C", "D", "E"],
        )

    def test_move_to_edge(self):
        ids = [self.db.add_item(self.pid, item_name=n) for n in "ABCDE"]
        self.db.move_items_to_edge(self.pid, [ids[1]], True)  # B to top
        self.assertEqual(
            [i["item_name"] for i in self.db.get_items(self.pid)],
            ["B", "A", "C", "D", "E"],
        )
        self.db.move_items_to_edge(self.pid, [ids[1]], False)  # B to bottom
        self.assertEqual(
            [i["item_name"] for i in self.db.get_items(self.pid)],
            ["A", "C", "D", "E", "B"],
        )

    def test_move_to_position(self):
        ids = [self.db.add_item(self.pid, item_name=n) for n in "ABCDE"]
        self.db.move_items_to_position(self.pid, [ids[4]], 2)  # E to row 2
        self.assertEqual(
            [i["item_name"] for i in self.db.get_items(self.pid)],
            ["A", "E", "B", "C", "D"],
        )

    def test_duplicate_inserts_adjacent_and_copies_flags(self):
        iid = self.db.add_item(
            self.pid, item_name="Valve", total_quantity=4, delivered_quantity=6,
            manual_hold=True, po_issued=True, variance_note="spare units",
        )
        [self.db.add_item(self.pid, item_name="Tail") for _ in range(2)]
        new_ids = self.db.duplicate_items(self.pid, [iid])
        self.assertEqual(len(new_ids), 1)
        items = self.db.get_items(self.pid)
        names = [i["item_name"] for i in items]
        self.assertEqual(names.index("Valve (Copy)"), names.index("Valve") + 1)
        copy = self.db.get_item(new_ids[0])
        self.assertEqual(copy["manual_hold"], 1)
        self.assertEqual(copy["po_issued"], 1)
        self.assertEqual(copy["variance_note"], "spare units")
        self.assertEqual(copy["status"], "On Hold")

    def test_duplicate_multi_select_order_preserved(self):
        ids = [self.db.add_item(self.pid, item_name=n) for n in "ABC"]
        self.db.duplicate_items(self.pid, [ids[2], ids[0]])  # C then A
        names = [i["item_name"] for i in self.db.get_items(self.pid)]
        # C copy lands right after C, A copy right after A
        self.assertEqual(names, ["A", "A (Copy)", "B", "C", "C (Copy)"])

    def test_update_item_recomputes_status(self):
        iid = self.db.add_item(self.pid, item_name="X", total_quantity=10)
        self.db.update_item(iid, requested_quantity=10)
        self.assertEqual(self.db.get_item(iid)["status"], "Requested")
        self.db.update_item(iid, delivered_quantity=10)
        self.assertEqual(self.db.get_item(iid)["status"], "Delivered")
        self.db.update_item(iid, manual_hold=True)
        self.assertEqual(self.db.get_item(iid)["status"], "On Hold")


class TestSoftDeleteAndTrash(unittest.TestCase):
    def setUp(self):
        self.db, self.tmp = make_db()

    def test_purge_item_removes_row_and_file(self):
        pid = self.db.add_project("P")
        iid = self.db.add_item(pid, item_name="Item")
        src = os.path.join(self.tmp, "doc.pdf")
        with open(src, "w") as f:
            f.write("x")
        self.db.add_attachment(iid, "PR", src)
        att = self.db.get_attachments(iid)[0]
        self.assertTrue(os.path.exists(att["file_path"]))
        self.db.purge_item(iid)
        self.assertIsNone(self.db.get_item(iid))
        self.assertFalse(os.path.exists(att["file_path"]))

    def test_purge_project_removes_everything(self):
        pid = self.db.add_project("P")
        iid = self.db.add_item(pid, item_name="Item")
        src = os.path.join(self.tmp, "doc2.pdf")
        with open(src, "w") as f:
            f.write("x")
        self.db.add_attachment(iid, "PO", src)
        att = self.db.get_attachments(iid)[0]
        self.db.purge_project(pid)
        con = sqlite3.connect(self.db.db_path)
        try:
            n_projects = con.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
            n_items = con.execute("SELECT COUNT(*) FROM items").fetchone()[0]
            n_atts = con.execute("SELECT COUNT(*) FROM attachments").fetchone()[0]
        finally:
            con.close()
        self.assertEqual((n_projects, n_items, n_atts), (0, 0, 0))
        self.assertFalse(os.path.exists(att["file_path"]))

    def test_restore_project_does_not_resurrect_earlier_deleted_items(self):
        pid = self.db.add_project("P")
        x = self.db.add_item(pid, item_name="Deleted earlier")
        y = self.db.add_item(pid, item_name="Alive")
        self.db.delete_item(x)
        time.sleep(1.1)  # ensure a different deleted_at second
        self.db.delete_project(pid)
        self.db.restore_project(pid)
        self.assertEqual(self.db.get_project(pid)["is_deleted"], 0)
        self.assertEqual(self.db.get_item(y)["is_deleted"], 0)
        self.assertEqual(self.db.get_item(x)["is_deleted"], 1)
        # ... and the project restore can be undone wholesale via trash
        self.db.delete_project(pid)
        self.db.restore_project(pid)
        self.assertEqual(self.db.get_item(y)["is_deleted"], 0)

    def test_delete_item_then_project_then_restore_project(self):
        pid = self.db.add_project("P")
        a = self.db.add_item(pid, item_name="A")
        self.db.delete_project(pid)
        self.db.restore_project(pid)
        self.assertEqual(self.db.get_item(a)["is_deleted"], 0)

    def test_supplier_soft_delete_keeps_items_linked(self):
        sid = self.db.add_supplier("Acme")
        pid = self.db.add_project("P")
        iid = self.db.add_item(pid, item_name="Pump", supplier_id=sid)
        self.db.delete_supplier(sid)
        self.assertEqual(self.db.get_item(iid)["supplier_name"], "Acme")
        self.assertNotIn(sid, [s["id"] for s in self.db.get_suppliers()])
        self.assertIn(sid, [s["id"] for s in self.db.get_suppliers(include_deleted=True)])


class TestMigrations(unittest.TestCase):
    def test_fresh_db_migration_is_idempotent(self):
        db, tmp = make_db()
        pid = db.add_project("P")
        db.add_item(pid, item_name="A")
        # Opening the same file again must not fail or change counts.
        db2 = Database(db.db_path, os.path.join(tmp, "att2"))
        self.assertEqual(len(db2.get_items(pid)), 1)

    def test_old_shaped_db_migrates(self):
        tmp = tempfile.mkdtemp(prefix="pt_old_")
        db_path = os.path.join(tmp, "project_tracker.db")
        con = sqlite3.connect(db_path)
        con.executescript(
            """
            CREATE TABLE projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                location TEXT, contractor TEXT, project_number TEXT,
                currency TEXT DEFAULT 'SAR', notes TEXT, created_date TEXT,
                project_group TEXT);
            CREATE TABLE suppliers (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                contact_person TEXT, phone TEXT, email TEXT, notes TEXT);
            CREATE TABLE items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL, item_name TEXT NOT NULL,
                pump_station TEXT, supplier_id INTEGER, unit TEXT,
                total_quantity REAL DEFAULT 0, requested_quantity REAL DEFAULT 0,
                delivered_quantity REAL DEFAULT 0, unit_cost REAL DEFAULT 0,
                remarks TEXT, status TEXT DEFAULT 'Not requested', last_updated TEXT,
                FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
                FOREIGN KEY (supplier_id) REFERENCES suppliers (id) ON DELETE SET NULL);
            CREATE TABLE attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER NOT NULL,
                category TEXT NOT NULL, file_path TEXT NOT NULL, original_name TEXT,
                uploaded_date TEXT,
                FOREIGN KEY (item_id) REFERENCES items (id) ON DELETE CASCADE);
            CREATE TABLE audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT, entity_type TEXT NOT NULL,
                entity_id INTEGER NOT NULL, entity_name TEXT, project_id INTEGER,
                action TEXT NOT NULL, field TEXT, old_value TEXT, new_value TEXT,
                changed_at TEXT NOT NULL);
            CREATE TABLE ai_chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT, scope_project_id INTEGER,
                role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL);
            INSERT INTO projects (name, created_date, project_group)
                VALUES ('Legacy', '2024-01-01 00:00:00', 'QUBA');
            INSERT INTO items (project_id, item_name) VALUES (1, 'Old item A');
            INSERT INTO items (project_id, item_name) VALUES (1, 'Old item B');
            """
        )
        con.commit()
        con.close()

        db = Database(db_path, os.path.join(tmp, "att"))

        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
        try:
            item_cols = {r["name"] for r in con.execute("PRAGMA table_info(items)")}
            proj_cols = {r["name"] for r in con.execute("PRAGMA table_info(projects)")}
            chat_cols = {r["name"] for r in con.execute("PRAGMA table_info(ai_chat_history)")}
            self.assertIn("sort_order", item_cols)
            self.assertIn("currency", item_cols)
            self.assertIn("manual_hold", item_cols)
            self.assertIn("is_deleted", item_cols)
            self.assertIn("group_id", proj_cols)
            self.assertIn("scope_group_id", chat_cols)
            indexes = {r["name"] for r in con.execute("SELECT name FROM sqlite_master WHERE type='index'")}
            self.assertIn("idx_chat_scope_group", indexes)
            # legacy group tag backfilled into a real group
            group = con.execute("SELECT * FROM project_groups WHERE name='QUBA'").fetchone()
            self.assertIsNotNone(group)
            proj = con.execute("SELECT * FROM projects WHERE id=1").fetchone()
            self.assertEqual(proj["group_id"], group["id"])
            # sort_order backfilled as a clean 1..N sequence
            orders = [r["sort_order"] for r in con.execute(
                "SELECT sort_order FROM items ORDER BY id")]
            self.assertEqual(orders, [1, 2])
        finally:
            con.close()

        # running migration again (idempotent) must not raise or duplicate
        Database(db_path, os.path.join(tmp, "att"))
        con = sqlite3.connect(db_path)
        try:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM project_groups").fetchone()[0], 1)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM items").fetchone()[0], 2)
        finally:
            con.close()


class TestSearch(unittest.TestCase):
    def setUp(self):
        self.db, self.tmp = make_db()
        self.p1 = self.db.add_project("Project One")
        self.p2 = self.db.add_project("Project Two")
        self.db.add_item(self.p1, item_name="Submersible Pump 100",
                         remarks="plate no. 55")
        self.db.add_item(self.p1, item_name="Pipe Fitting", remarks="\u0644\u0648\u062D HDPE \u0642\u0637\u0631 100")
        self.db.add_item(self.p2, item_name="Gate Valve", unit="nos")

    def test_contains_all_words_any_order(self):
        res = self.db.search_items_across_projects("100 HDPE", mode="include")
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["item_name"], "Pipe Fitting")
        self.assertIn("Remarks", res[0]["matched_fields"])

    def test_contains_exact_phrase_is_order_sensitive(self):
        self.assertEqual(len(self.db.search_items_across_projects("HDPE 100", mode="contains")), 0)
        self.assertEqual(len(self.db.search_items_across_projects("\u0642\u0637\u0631 100", mode="contains")), 1)

    def test_exact_match_mode(self):
        self.assertEqual(len(self.db.search_items_across_projects("gate valve", mode="equal")), 1)
        self.assertEqual(len(self.db.search_items_across_projects("gate", mode="equal")), 0)

    def test_field_restriction(self):
        res = self.db.search_items_across_projects("pump", fields=["item_name"])
        self.assertEqual(len(res), 1)
        res = self.db.search_items_across_projects("55", fields=["remarks"])
        self.assertEqual(len(res), 1)

    def test_scope_restriction(self):
        res = self.db.search_items_across_projects("valve", project_ids=[self.p2])
        self.assertEqual(len(res), 1)
        res = self.db.search_items_across_projects("valve", project_ids=[self.p1])
        self.assertEqual(len(res), 0)

    def test_arabic_query_matches_arabic_content(self):
        res = self.db.search_items_across_projects("\u0644\u0648\u062D", mode="include")
        self.assertEqual(len(res), 1)

    def test_deleted_items_are_not_searched(self):
        items = self.db.get_items(self.p1)
        self.db.delete_item(items[0]["id"])
        res = self.db.search_items_across_projects("submersible")
        self.assertEqual(len(res), 0)


class TestBulkFindReplace(unittest.TestCase):
    def setUp(self):
        self.db, self.tmp = make_db()
        self.pid = self.db.add_project("P")
        self.a = self.db.add_item(self.pid, item_name="Puddle Pice A", remarks="ok")
        self.b = self.db.add_item(self.pid, item_name="Puddle Pice B", remarks="Pice")
        self.c = self.db.add_item(self.pid, item_name="Fine already", remarks="Pice")

    def test_count_matches(self):
        ids = [self.a, self.b, self.c]
        self.assertEqual(self.db.count_find_replace_matches(ids, "item_name", "Pice"), 2)
        self.assertEqual(self.db.count_find_replace_matches(ids, "remarks", "pice"), 2)

    def test_replace_only_touching_matching_items(self):
        ids = [self.a, self.b, self.c]
        updated = self.db.bulk_find_replace(ids, "item_name", "Pice", "Piece")
        self.assertEqual(updated, 2)
        self.assertEqual(self.db.get_item(self.a)["item_name"], "Puddle Piece A")
        self.assertEqual(self.db.get_item(self.b)["item_name"], "Puddle Piece B")
        self.assertEqual(self.db.get_item(self.c)["item_name"], "Fine already")

    def test_case_sensitive_mode(self):
        updated = self.db.bulk_find_replace([self.a, self.b, self.c], "remarks",
                                            "Pice", "Piece", case_sensitive=True)
        self.assertEqual(updated, 2)

    def test_rejects_disallowed_field(self):
        with self.assertRaises(ValueError):
            self.db.bulk_find_replace([self.a], "unit_cost", "1", "2")


class TestChatHistoryAndDashboard(unittest.TestCase):
    def setUp(self):
        self.db, self.tmp = make_db()

    def test_chat_history_scopes(self):
        pid = self.db.add_project("P")
        self.db.save_chat_message(pid, "user", "hello project")
        self.db.save_chat_message(None, "user", "hello all", scope_group_id=None)
        self.db.save_chat_message(None, "user", "hello group", scope_group_id=7)
        proj = self.db.get_chat_history(pid)
        self.assertEqual([m["content"] for m in proj], ["hello project"])
        allc = self.db.get_chat_history(None)
        self.assertEqual([m["content"] for m in allc], ["hello all"])
        grp = self.db.get_chat_history(None, scope_group_id=7)
        self.assertEqual([m["content"] for m in grp], ["hello group"])
        self.db.clear_chat_history(pid)
        self.assertEqual(self.db.get_chat_history(pid), [])

    def test_dashboard_summary_counts(self):
        pid = self.db.add_project("P")
        self.db.add_item(pid, item_name="A", total_quantity=10, unit_cost=2, currency="SAR")
        self.db.add_item(pid, item_name="B", total_quantity=5, unit_cost=0)
        self.db.add_item(pid, item_name="C", total_quantity=0)
        summary = self.db.get_dashboard_summary()
        self.assertEqual(summary["item_count"], 3)
        self.assertEqual(summary["missing_cost_count"], 2)
        self.assertEqual(summary["status_counts"]["Not requested"], 3)
        self.assertAlmostEqual(summary["value_by_currency"]["SAR"], 20.0)
        self.assertAlmostEqual(summary["value_by_currency"]["?"], 0.0)

    def test_dashboard_stale_items(self):
        pid = self.db.add_project("P")
        stale = self.db.add_item(pid, item_name="Forgotten")
        fresh = self.db.add_item(pid, item_name="Fresh")
        con = sqlite3.connect(self.db.db_path)
        try:
            con.execute("UPDATE items SET last_updated='2020-01-01 10:00:00' WHERE id=?", (stale,))
            con.commit()
        finally:
            con.close()
        summary = self.db.get_dashboard_summary(stale_days=14)
        ids = [r["id"] for r in summary["stale_items"]]
        self.assertIn(stale, ids)
        self.assertNotIn(fresh, ids)
        row = next(r for r in summary["stale_items"] if r["id"] == stale)
        self.assertEqual(row["project_name"], "P")
        self.assertGreater(row["days_stale"], 365)


class TestActivityLog(unittest.TestCase):
    def test_updates_are_recorded(self):
        db, tmp = make_db()
        pid = db.add_project("P")
        iid = db.add_item(pid, item_name="A", total_quantity=1)
        db.update_item(iid, requested_quantity=1)
        rows = db.get_activity(project_id=pid)
        actions = [r["action"] for r in rows]
        self.assertIn("created", actions)
        self.assertIn("updated", actions)
        fields = [r["field"] for r in rows if r["action"] == "updated"]
        self.assertIn("requested_quantity", fields)


if __name__ == "__main__":
    unittest.main()
