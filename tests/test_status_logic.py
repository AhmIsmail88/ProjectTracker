# -*- coding: utf-8 -*-
"""Status computation + helper edge cases (constants.compute_status)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from constants import (
    compute_status, is_over_supplied, is_delivered_without_request,
    is_over_requested, remaining_to_request, remaining_to_deliver,
)


class TestComputeStatus(unittest.TestCase):
    def test_all_zero_is_not_requested(self):
        self.assertEqual(compute_status(0, 0, 0), "Not requested")

    def test_requested_less_than_total(self):
        self.assertEqual(compute_status(10, 4, 0), "Partially Requested")

    def test_requested_equals_total(self):
        self.assertEqual(compute_status(10, 10, 0), "Requested")

    def test_requested_over_total_is_requested_status_with_warning(self):
        self.assertEqual(compute_status(10, 12, 0), "Requested")
        self.assertTrue(is_over_requested(10, 12))
        self.assertFalse(is_over_requested(10, 10))

    def test_partially_delivered(self):
        self.assertEqual(compute_status(10, 10, 4), "Partially Delivered")

    def test_fully_delivered(self):
        self.assertEqual(compute_status(10, 10, 10), "Delivered")

    def test_over_delivered_is_delivered_with_over_supply_warning(self):
        self.assertEqual(compute_status(10, 10, 12), "Delivered")
        self.assertTrue(is_over_supplied(10, 12))
        self.assertFalse(is_over_supplied(10, 10))

    def test_delivered_with_zero_total(self):
        # No total scope recorded but something delivered: stays partial
        # status-wise, and the over-supply warning must fire.
        self.assertEqual(compute_status(0, 0, 5), "Partially Delivered")
        self.assertTrue(is_over_supplied(0, 5))

    def test_delivered_without_request_warning(self):
        self.assertTrue(is_delivered_without_request(0, 5))
        self.assertTrue(is_delivered_without_request(0, 0.5))
        self.assertFalse(is_delivered_without_request(1, 5))
        self.assertFalse(is_delivered_without_request(0, 0))

    def test_manual_hold_wins_over_everything(self):
        self.assertEqual(compute_status(10, 10, 10, manual_hold=True), "On Hold")
        self.assertEqual(compute_status(0, 0, 0, manual_hold=True), "On Hold")

    def test_po_issued_beats_requested(self):
        self.assertEqual(compute_status(10, 10, 0, po_issued=True), "PO Issued")

    def test_po_ignored_once_delivering(self):
        self.assertEqual(compute_status(10, 10, 4, po_issued=True), "Partially Delivered")

    def test_none_quantities_treated_as_zero(self):
        self.assertEqual(compute_status(None, None, None), "Not requested")
        self.assertEqual(remaining_to_request(None, None), 0)

    def test_remaining_helpers_clamp_at_zero(self):
        self.assertEqual(remaining_to_request(10, 4), 6)
        self.assertEqual(remaining_to_request(10, 12), 0)
        self.assertEqual(remaining_to_deliver(10, 3), 7)
        self.assertEqual(remaining_to_deliver(10, 15), 0)


if __name__ == "__main__":
    unittest.main()
