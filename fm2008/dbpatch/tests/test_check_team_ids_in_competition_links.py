#!/usr/bin/env python3
"""Tests for direct club-ID occurrences in typed competition links."""
from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from check_team_ids_in_competition_links import link_role_positions  # noqa: E402


class TeamLinkRoleTests(unittest.TestCase):
    def test_id_can_be_detected_in_either_competition_endpoint(self):
        left_id, right_id = 130488, 8050940
        data = (
            b"prefix"
            + b"\x03" + struct.pack("<I", left_id) + b"\x04"
            + struct.pack("<I", right_id)
            + b"suffix"
        )
        self.assertEqual(link_role_positions(data, left_id), ([6], []))
        self.assertEqual(link_role_positions(data, right_id), ([], [6]))

    def test_id_outside_exact_pair_endpoint_is_not_counted(self):
        entity_id = 130523
        data = b"\x02" + struct.pack("<I", entity_id) + b"\x05"
        self.assertEqual(link_role_positions(data, entity_id), ([], []))


if __name__ == "__main__":
    unittest.main()
