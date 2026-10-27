#!/usr/bin/env python3
"""Проверки точных границ строк и ссылок в ростер-анализаторе."""
from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from compare_roster_regions import (  # noqa: E402
    string_id_for_name,
    localized_name,
    zone_links_before_name,
)


class RosterRegionAnalysisTests(unittest.TestCase):
    def test_name_match_marks_reserve_suffix_and_prefers_exact_name(self):
        text = "Черноморец Новороссийск"
        annotated = text + " (Д)"
        annotated_blob = (
            struct.pack("<II", 476541, len(annotated))
            + annotated.encode("utf-16-le") + b"\x00\x00"
        )
        exact_blob = (
            struct.pack("<II", 1301102, len(text))
            + text.encode("utf-16-le") + b"\x00\x00"
        )
        self.assertEqual(string_id_for_name(annotated_blob, text), (476541, True))
        self.assertEqual(string_id_for_name(annotated_blob, annotated), (476541, False))
        self.assertEqual(
            string_id_for_name(annotated_blob + exact_blob, text), (1301102, False)
        )

    def test_name_match_rejects_unrelated_longer_name(self):
        text = "Ротор Волгоград"
        unrelated = "Ротор Волгоградский"
        blob = (
            struct.pack("<II", 476256, len(unrelated))
            + unrelated.encode("utf-16-le") + b"\x00\x00"
        )
        self.assertIsNone(string_id_for_name(blob, text))

    def test_localized_name_rejects_unrelated_reused_id(self):
        russian_entry = struct.pack("<II", 16777220, len("Зеленоград"))
        russian_entry += "Зеленоград".encode("utf-16-le") + b"\x00\x00"
        unrelated = "St. Pölten"
        entry = struct.pack("<II", 16777220, len(unrelated))
        entry += unrelated.encode("utf-16-le") + b"\x00\x00"
        self.assertIsNone(
            localized_name([russian_entry, entry], 16777220, unrelated.encode("utf-16-le"), "Зеленоград")
        )

    def test_localized_name_accepts_matching_transliteration(self):
        candidate = "Rotor Volgograd (D)"
        entry = struct.pack("<II", 476256, len(candidate))
        entry += candidate.encode("utf-16-le") + b"\x00\x00"
        self.assertEqual(
            localized_name(
                [entry], 476256, candidate.encode("utf-16-le"), "Ротор Волгоград"
            ),
            candidate,
        )

    def test_zone_links_accept_exact_48_and_49_byte_gaps(self):
        name = "Sportakademclub Moscow"
        encoded = name.encode("utf-16-le") + b"\x00\x00"
        for gap in (48, 49):
            with self.subTest(gap=gap):
                data = bytearray(160)
                name_pos = 80
                start = name_pos - gap
                data[start:start + 9] = (
                    b"\x03" + struct.pack("<I", 130488)
                    + b"\x04" + struct.pack("<I", 8050940)
                )
                data[name_pos:name_pos + len(encoded)] = encoded
                self.assertEqual(
                    zone_links_before_name(bytes(data), name),
                    {(130488, 8050940, start)},
                )

    def test_zone_links_reject_nearby_but_wrong_gaps(self):
        name = "Sportakademclub Moscow"
        encoded = name.encode("utf-16-le") + b"\x00\x00"
        for gap in (47, 50):
            with self.subTest(gap=gap):
                data = bytearray(160)
                name_pos = 80
                start = name_pos - gap
                data[start:start + 9] = (
                    b"\x03" + struct.pack("<I", 130488)
                    + b"\x04" + struct.pack("<I", 8050940)
                )
                data[name_pos:name_pos + len(encoded)] = encoded
                self.assertEqual(zone_links_before_name(bytes(data), name), set())


if __name__ == "__main__":
    unittest.main()
