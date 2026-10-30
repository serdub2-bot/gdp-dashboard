#!/usr/bin/env python3
"""Тесты эвристик read-only-анализатора связей между группами."""
from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from compare_group_links import group_links, locate_marker, nearby_utf16_text  # noqa: E402


class GroupLinkAnalysisTests(unittest.TestCase):
    def test_locate_marker_requires_id_and_exact_marker(self):
        data = bytearray(96)
        data[8:12] = struct.pack("<I", 72)
        marker = bytes.fromhex("00 00 00 ff 7f c5 6e c5 6e")
        data[12:21] = marker
        self.assertEqual(locate_marker(bytes(data), 72, {marker}), (8, marker))
        self.assertIsNone(locate_marker(bytes(data), 73, {marker}))
        self.assertIsNone(locate_marker(bytes(data), 72, {b"x" * 9}))

    def test_nearby_utf16_text_decodes_club_name_after_pair(self):
        data = bytearray(128)
        pair_start = 11
        text = "Sportakademclub Moscow".encode("utf-16-le") + b"\x00\x00"
        start = pair_start + 49
        data[start:start + len(text)] = text
        self.assertEqual(nearby_utf16_text(bytes(data), pair_start), "Sportakademclub Moscow")

    def test_nearby_utf16_text_ignores_non_text(self):
        self.assertIsNone(nearby_utf16_text(bytes(range(128)), 8))

    def test_group_links_returns_related_id_and_club_name_hint(self):
        group_id, related_id, pair_start = 130488, 8050901, 8
        data = bytearray(160)
        data[pair_start:pair_start + 10] = (
            b"\x03" + struct.pack("<I", group_id) + b"\x04"
            + struct.pack("<I", related_id)
        )
        name = "Sportakademclub Moscow".encode("utf-16-le") + b"\x00\x00"
        data[pair_start + 49:pair_start + 49 + len(name)] = name
        self.assertEqual(
            group_links(bytes(data), group_id),
            [(pair_start, related_id, "Sportakademclub Moscow")],
        )
        self.assertEqual(group_links(bytes(data), 130487), [])


if __name__ == "__main__":
    unittest.main()
