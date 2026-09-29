"""Tests for the project time schedule API (schedule_activities)."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from database import Database


class ScheduleApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pt_sched_test_")
        self.db = Database(config.db_path_for(self.tmp), config.attachments_dir_for(self.tmp))
        self.project_id = self.db.add_project("Schedule Test", project_number="PR-900")

    def _names(self):
        return [a["name"] for a in self.db.get_schedule_activities(self.project_id)]

    # ------------------------------------------------------------------ #
    def test_add_and_list_in_insertion_order(self):
        self.db.add_schedule_activity(self.project_id, "Mobilisation",
                                      start_date="2026-01-01", end_date="2026-01-10")
        self.db.add_schedule_activity(self.project_id, "Excavation",
                                      start_date="2026-01-11", end_date="2026-02-01")
        self.db.add_schedule_activity(self.project_id, "Handover",
                                      start_date="2026-02-02", end_date="2026-02-02",
                                      milestone=True)
        self.assertEqual(self._names(), ["Mobilisation", "Excavation", "Handover"])
        rows = self.db.get_schedule_activities(self.project_id)
        self.assertEqual(rows[-1]["milestone"], 1)
        self.assertEqual(rows[0]["phase"], "")

    def test_name_is_required(self):
        with self.assertRaises(ValueError):
            self.db.add_schedule_activity(self.project_id, "   ")

    def test_end_before_start_is_rejected_on_add_and_update(self):
        with self.assertRaises(ValueError):
            self.db.add_schedule_activity(self.project_id, "Bad",
                                          start_date="2026-03-10", end_date="2026-03-01")
        activity_id = self.db.add_schedule_activity(
            self.project_id, "Good", start_date="2026-03-01", end_date="2026-03-10")
        with self.assertRaises(ValueError):
            self.db.update_schedule_activity(activity_id, end_date="2026-02-01")
        # the bad edit must not have been stored
        self.assertEqual(self.db.get_schedule_activity(activity_id)["end_date"], "2026-03-10")

    def test_progress_is_clamped(self):
        activity_id = self.db.add_schedule_activity(self.project_id, "A", progress=150)
        self.assertEqual(self.db.get_schedule_activity(activity_id)["progress"], 100)
        self.db.update_schedule_activity(activity_id, progress=-20)
        self.assertEqual(self.db.get_schedule_activity(activity_id)["progress"], 0)
        self.db.update_schedule_activity(activity_id, progress=45)
        self.assertEqual(self.db.get_schedule_activity(activity_id)["progress"], 45)

    def test_update_whitelist_ignores_unknown_columns(self):
        activity_id = self.db.add_schedule_activity(self.project_id, "A", phase="Civil")
        self.db.update_schedule_activity(activity_id, phase="MEP", project_id=999, nonsense=1)
        row = self.db.get_schedule_activity(activity_id)
        self.assertEqual(row["phase"], "MEP")
        self.assertEqual(row["project_id"], self.project_id)

    def test_soft_delete_and_restore(self):
        keep = self.db.add_schedule_activity(self.project_id, "Keep")
        drop = self.db.add_schedule_activity(self.project_id, "Drop")
        self.db.delete_schedule_activity(drop)
        self.assertEqual(self._names(), ["Keep"])
        self.db.restore_schedule_activity(drop)
        self.assertEqual(self._names(), ["Keep", "Drop"])
        # a restored row keeps its project
        self.assertEqual(self.db.get_schedule_activity(drop)["project_id"], self.project_id)

    def test_move_up_and_down_respects_the_edges(self):
        ids = [self.db.add_schedule_activity(self.project_id, f"A{i}") for i in range(3)]
        self.db.move_schedule_activity(self.project_id, ids[2], -1)
        self.assertEqual(self._names(), ["A0", "A2", "A1"])
        self.db.move_schedule_activity(self.project_id, ids[2], +1)
        self.assertEqual(self._names(), ["A0", "A1", "A2"])
        # moving the first up, or the last down, changes nothing
        self.db.move_schedule_activity(self.project_id, ids[0], -1)
        self.db.move_schedule_activity(self.project_id, ids[2], +1)
        self.assertEqual(self._names(), ["A0", "A1", "A2"])

    def test_reorder_by_explicit_order(self):
        ids = [self.db.add_schedule_activity(self.project_id, f"B{i}") for i in range(3)]
        self.db.reorder_schedule_activities([ids[2], ids[0], ids[1]])
        self.assertEqual(self._names(), ["B2", "B0", "B1"])
        orders = [a["sort_order"] for a in self.db.get_schedule_activities(self.project_id)]
        self.assertEqual(orders, [1, 2, 3])

    def test_activities_are_project_scoped(self):
        other = self.db.add_project("Other", project_number="PR-901")
        self.db.add_schedule_activity(self.project_id, "Mine")
        self.db.add_schedule_activity(other, "Theirs")
        self.assertEqual(self._names(), ["Mine"])
        self.assertEqual([a["name"] for a in self.db.get_schedule_activities(other)], ["Theirs"])

    def test_changes_are_audited(self):
        activity_id = self.db.add_schedule_activity(self.project_id, "Audited")
        self.db.update_schedule_activity(activity_id, progress=30)
        entries = self.db.get_activity(entity_type="schedule", entity_id=activity_id)
        actions = {(e["action"], e["field"]) for e in entries}
        self.assertIn(("created", None), actions)
        self.assertIn(("updated", "progress"), actions)


if __name__ == "__main__":
    unittest.main()
