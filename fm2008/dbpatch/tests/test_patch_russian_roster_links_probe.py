from __future__ import annotations

import struct
import unittest

from patch_russian_roster_links_probe import (
    A5_MARKER,
    Edit,
    apply_edits,
    find_a5_team_record,
)


class TeamLinkProbeTests(unittest.TestCase):
    def make_record(self, team_id: int, offset: int = 32, ordinal: int = 1234) -> bytearray:
        data = bytearray(128)
        struct.pack_into("<I", data, offset - 4, ordinal)
        struct.pack_into("<I", data, offset, team_id)
        data[offset + 4:offset + 8] = A5_MARKER
        data[offset + 12:offset + 16] = bytes.fromhex("00 00 2c 00")
        return data

    def test_finds_only_a5_record_and_requires_unique_match(self) -> None:
        team_id = 130517
        data = self.make_record(team_id)
        # A duplicate plain ID outside an A5 row is not considered an A5 record.
        struct.pack_into("<I", data, 96, team_id)
        self.assertEqual(find_a5_team_record(bytes(data), team_id), 32)
        self.assertIsNone(find_a5_team_record(bytes(data), 999999))

    def test_ambiguous_a5_records_abort(self) -> None:
        team_id = 130517
        data = self.make_record(team_id, 24, 12)
        second = self.make_record(team_id, 80, 13)
        data[64:128] = second[64:128]
        with self.assertRaisesRegex(RuntimeError, "multiple A5-shaped rows"):
            find_a5_team_record(bytes(data), team_id)

    def test_patch_changes_only_the_serialized_plus54_word(self) -> None:
        team_id = 130517
        data = bytes(self.make_record(team_id))
        edit = Edit(
            team_id=team_id,
            zone="Запад",
            team_name="Динамо Вологда",
            comp_id=130488,
            comp_slot=179,
            id_offset=32,
            old=bytes.fromhex("00 00 2c 00"),
            new=(179).to_bytes(4, "big"),
        )
        patched = apply_edits(data, [edit])
        self.assertEqual(len(patched), len(data))
        self.assertEqual(patched[44:48], bytes.fromhex("00 00 00 b3"))
        changes = {i for i, (a, b) in enumerate(zip(data, patched)) if a != b}
        self.assertLessEqual(changes, {44, 45, 46, 47})
        self.assertEqual(patched[:44], data[:44])
        self.assertEqual(patched[48:], data[48:])

    def test_comp_slots_over_255_keep_big_endian_word(self) -> None:
        self.assertEqual((942).to_bytes(4, "big"), bytes.fromhex("00 00 03 ae"))


if __name__ == "__main__":
    unittest.main()
