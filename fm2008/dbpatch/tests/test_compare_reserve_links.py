#!/usr/bin/env python3
"""Проверки извлечения `(D)`-имён и их точных бинарных ссылок."""
from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from compare_reserve_links import names_with_suffix, reserve_link_rows  # noqa: E402


def lang_entry(string_id: int, text: str) -> bytes:
    return (
        struct.pack("<II", string_id, len(text))
        + text.encode("utf-16-le")
        + b"\x00\x00"
    )


def add_pair_and_name(
    data: bytearray, pair_start: int, gap: int, name: str, zone: int, lower: int
) -> None:
    data[pair_start:pair_start + 9] = (
        b"\x03" + struct.pack("<I", zone) + b"\x04" + struct.pack("<I", lower)
    )
    encoded = name.encode("utf-16-le") + b"\x00\x00"
    name_start = pair_start + gap
    data[name_start:name_start + len(encoded)] = encoded


class ReserveLinkAnalysisTests(unittest.TestCase):
    def test_names_with_suffix_requires_full_record_boundary(self):
        valid = lang_entry(900, "Lada Togliatti (D)")
        embedded = lang_entry(901, "Old Lada Togliatti (D) spare")
        self.assertEqual(names_with_suffix(valid + embedded), {"Lada Togliatti (D)"})

    def test_reserve_link_rows_separate_parent_and_reserve_records(self):
        parent = "Lada Togliatti"
        reserve = parent + " (D)"
        english = lang_entry(900, reserve)
        server = bytearray(320)
        add_pair_and_name(server, 16, 49, parent, 8055759, 8050904)
        add_pair_and_name(server, 168, 48, reserve, 8055759, 8050904)

        names, rows = reserve_link_rows(english, bytes(server))
        self.assertEqual(names, {reserve})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], reserve)
        self.assertEqual(rows[0][1], {(8055759, 8050904, 16)})
        self.assertEqual(rows[0][2], {(8055759, 8050904, 168)})


if __name__ == "__main__":
    unittest.main()
