#!/usr/bin/env python3
"""Тесты контейнера и патчера: проверка roundtrip и защитных проверок.

Запуск:  python3 tests/test_si_db.py
        (или python3 -m pytest tests -q, если установлен pytest)
"""
from __future__ import annotations

import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from si_db import Container, DbError, utf16_offsets, zlib_streams  # noqa: E402
import patch as patcher  # noqa: E402


def make_dat(payload: bytes, version: bytes = b"\x77\x04\x00") -> bytes:
    """Собрать минимальный .dat: заголовок 9 байт + zlib."""
    return b"\x02\x01tad." + version + zlib.compress(payload, 9)


class ContainerTests(unittest.TestCase):
    def test_roundtrip_identical(self):
        payload = b"".join(struct.pack("<II", i, i * 3) for i in range(5000))
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "client_db.dat"
            src.write_bytes(make_dat(payload))

            cont = Container.load(src)
            self.assertTrue(cont.compressed)
            self.assertEqual(cont.tag, b"tad.")
            self.assertEqual(cont.version, b"\x77\x04\x00")
            self.assertEqual(cont.decompressed(), payload)

            out = cont.save(Path(tmp) / "out" / "client_db.dat", payload)
            self.assertEqual(Container.load(out).decompressed(), payload)

    def test_header_preserved(self):
        payload = b"x" * 1000
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "a.dat"
            raw = make_dat(payload, version=b"\x01\x00\x00")
            src.write_bytes(raw)
            out = Container.load(src).save(Path(tmp) / "b.dat", b"y" * 1000)
            self.assertEqual(out.read_bytes()[:9], raw[:9])

    def test_bad_magic(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "x.dat"
            src.write_bytes(b"not a db file at all")
            with self.assertRaises(DbError):
                Container.load(src)

    def test_zlib_streams_found(self):
        blob = (b"\x00" * 64) + zlib.compress(b"A" * 80_000, 9) + (b"\xff" * 64) + \
               zlib.compress(b"B" * 80_000, 9)
        streams = zlib_streams(blob)
        self.assertEqual(len(streams), 2)
        self.assertEqual(streams[0][0], 64)
        self.assertEqual(streams[0][1], b"A" * 80_000)


class PatchGuardTests(unittest.TestCase):
    def test_write_u32_ok(self):
        data = bytearray(struct.pack("<II", 5, 7))
        report: list[str] = []
        out = patcher.apply_byte_ops(data, [
            {"type": "write_u32", "offset": 0, "expect": 5, "value": 6},
        ], report)
        self.assertEqual(struct.unpack_from("<I", out, 0)[0], 6)
        self.assertEqual(len(report), 1)

    def test_expect_mismatch_raises(self):
        data = bytearray(struct.pack("<II", 5, 7))
        with self.assertRaises(DbError):
            patcher.apply_byte_ops(data, [
                {"type": "write_u32", "offset": 0, "expect": 99, "value": 1},
            ], [])

    def test_write_bytes_length_guard(self):
        data = bytearray(b"ABCD")
        with self.assertRaises(DbError):
            patcher.apply_byte_ops(data, [
                {"type": "write_bytes", "offset": 0, "expect": "41424344", "data": "41"},
            ], [])


class StringPatchTests(unittest.TestCase):
    def test_rename_keeps_size(self):
        blob = zlib.compress("__test__".encode("utf-16-le") * 1 + b"", 9)
        head = b"\x02\x01tad." + b"\x77\x04\x00"
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "lang_db.dat"
            src.write_bytes(head + blob)
            # наша утилита ищет русскую таблицу; подложим её вручную через ту же функцию
            ru = "Второй дивизион - Волга".encode("utf-16-le")
            filler = ("я" * 30000).encode("utf-16-le")
            src.write_bytes(head + zlib.compress(ru + b"\x00" * 200 + filler, 9))
            ops = [{"type": "rename_string", "expect": "Второй дивизион - Волга",
                    "data": "Третья лига", "max_hits": 1}]
            out_file = patcher.apply_string_ops(src, ops, Path(tmp) / "out", [])
            self.assertIsNotNone(out_file)
            data = zlib.decompress(out_file.read_bytes()[9:])
            self.assertTrue(data.startswith("Третья лига".encode("utf-16-le")))
            # длина блока не изменилась — смещения не поехали
            self.assertEqual(len(data), len(ru) + 200 + 60000)

    def test_utf16_offsets(self):
        blob = "abc Название abc".encode("utf-16-le")
        self.assertEqual(len(utf16_offsets(blob, "abc")), 2)
        self.assertEqual(utf16_offsets(blob, "нет такой"), [])



class ExePatchTests(unittest.TestCase):
    def test_stub_registers_all_zones_at_same_tier(self):
        import patch_exe
        stub = patch_exe.build_stub()
        self.assertEqual([tier for _, tier, _ in patch_exe.SECOND_ZONES], [2] * 5)
        for comp_id, _, _ in patch_exe.SECOND_ZONES:
            self.assertEqual(stub.count(struct.pack("<I", comp_id)), 1)
        self.assertEqual(stub.count(b"\xE8"), 6)  # 5 zones + original First division

    def test_parent_group_stub_matches_spanish_registration_shape(self):
        import build_parent_group_release as candidate
        import patch_exe
        stub = candidate.build_stub()
        self.assertEqual(stub.count(struct.pack("<I", candidate.PARENT_ID)), 1)
        self.assertEqual(stub.count(b"\xE8"), 2)  # parent + original First division
        self.assertEqual(candidate.PARENT_TIER, 2)
        self.assertEqual(len(candidate.FLAG_SITES), 5)
        self.assertIn(b"\x6A\x02\x68" + struct.pack("<I", candidate.PARENT_ID), stub)
        self.assertIn(patch_exe.jmp_rel(
            patch_exe.STUB_VA + len(stub) - 5, patch_exe.RETURN_VA), stub)

    def test_parent_group_patch_changes_only_declared_sites(self):
        import build_parent_group_release as candidate
        import patch_exe
        length = patch_exe.STUB_RAW + patch_exe.STUB_SPACE
        source = bytearray(length)
        source[patch_exe.HOOK_RAW:patch_exe.HOOK_RAW + 5] = patch_exe.ORIGINAL_HOOK
        source[patch_exe.STUB_RAW:patch_exe.STUB_RAW + patch_exe.STUB_SPACE] = b"\x90" * patch_exe.STUB_SPACE
        for site in candidate.FLAG_SITES.values():
            source[site:site + 2] = candidate.FLAG_FROM
        patched = candidate.patch_bytes(bytes(source))
        candidate.verify_bytes(bytes(source), patched)
        for site in candidate.FLAG_SITES.values():
            self.assertEqual(patched[site:site + 2], candidate.FLAG_TO)
        self.assertEqual(len(source), len(patched))

    def test_flag4_parent_probe_is_one_isolated_registration(self):
        import build_flag4_parent_probe as candidate
        import patch_exe
        stub = candidate.build_stub()
        original_call = b"\x8B\xCE" + patch_exe.call_rel(
            patch_exe.STUB_VA + 2, patch_exe.REGISTER_VA
        )
        parent_args = (b"\x6A\x04\x6A\x02\x68"
                       + struct.pack("<I", candidate.PARENT_ID))
        self.assertTrue(stub.startswith(original_call))
        self.assertIn(parent_args, stub)
        self.assertEqual(stub.count(b"\xE8"), 2)
        self.assertEqual((candidate.PARENT_TIER, candidate.PARENT_FLAGS), (2, 4))

        length = patch_exe.STUB_RAW + patch_exe.STUB_SPACE
        source = bytearray(length)
        source[patch_exe.HOOK_RAW:patch_exe.HOOK_RAW + 5] = patch_exe.ORIGINAL_HOOK
        source[patch_exe.STUB_RAW:patch_exe.STUB_RAW + patch_exe.STUB_SPACE] = b"\x90" * patch_exe.STUB_SPACE
        patched = candidate.patch_bytes(bytes(source))
        candidate.verify_bytes(bytes(source), patched)
        self.assertEqual(len(source), len(patched))

    def test_flag4_fixed_groups_probe_changes_only_five_range_sentinels(self):
        import build_flag4_fixed_groups_probe as candidate
        import patch_exe
        length = patch_exe.STUB_RAW + patch_exe.STUB_SPACE
        source = bytearray(length)
        source[patch_exe.HOOK_RAW:patch_exe.HOOK_RAW + 5] = patch_exe.ORIGINAL_HOOK
        source[patch_exe.STUB_RAW:patch_exe.STUB_RAW + patch_exe.STUB_SPACE] = b"\x90" * patch_exe.STUB_SPACE
        for site in candidate.FLAG_SITES.values():
            source[site:site + 2] = candidate.FLAG_FROM
        patched = candidate.patch_bytes(bytes(source))
        candidate.verify_bytes(bytes(source), patched)
        for site in candidate.FLAG_SITES.values():
            self.assertEqual(patched[site:site + 2], candidate.FLAG_TO)
        self.assertEqual(len(source), len(patched))


class ActivateTests(unittest.TestCase):
    """Логика плана патча: сборка правок и их применение."""

    @staticmethod
    def make_record(comp_id: int, level: int) -> bytes:
        rec = bytearray(54)
        rec[0:4] = b"\x00\x00\x00\x00"
        rec[4:8] = struct.pack("<I", 1)
        rec[8:12] = struct.pack("<I", comp_id)
        rec[12:18] = b"\x00\x00\x00\xff\x7f\x8c"
        rec[8 + 23] = level
        return bytes(rec)

    def build(self, levels: dict[int, int]) -> bytes:
        return b"\x00" * 32 + b"".join(self.make_record(i, l) for i, l in levels.items())

    def test_second_zone_ids_match_exe_registrations(self):
        import activate
        self.assertEqual(set(activate.SECOND), {130488, 130489, 130490, 130491, 8055759})

    def test_second_zones_set_to_three(self):
        import activate
        ids = list(activate.SECOND)
        data = self.build({i: 2 for i in ids})
        ops = activate.build_ops(data, "second3")
        self.assertEqual(len(ops), len(ids))
        patched = activate.apply_ops(data, ops)
        activate.verify(data, patched, ops)
        for op in ops:
            self.assertEqual(patched[op["offset"]], 3)

    def test_idempotent_when_already_patched(self):
        import activate
        ids = list(activate.SECOND)
        data = self.build({i: 3 for i in ids})
        self.assertEqual(activate.build_ops(data, "second3"), [])

    def test_missing_competition_raises(self):
        import activate
        with self.assertRaises(Exception):
            activate.build_ops(b"\x00" * 200, "second3")

    def test_verify_catches_stray_change(self):
        import activate
        ids = list(activate.SECOND)
        data = self.build({i: 2 for i in ids})
        ops = activate.build_ops(data, "second3")
        bad = bytearray(activate.apply_ops(data, ops))
        bad[1] ^= 0xFF
        with self.assertRaises(Exception):
            activate.verify(data, bytes(bad), ops)


if __name__ == "__main__":
    unittest.main(verbosity=2)
