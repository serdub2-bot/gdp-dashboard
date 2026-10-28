#!/usr/bin/env python3
"""Build a reversible FM2008 8.0.2 database probe for the verified Russian roster subset.

The probe changes only serialized TEAM+0x54 in A5-form records whose exact Russian
club names map to a unique 2007 Russian zone in the repository CSV. It writes the
COMP manager-slot reference using the confirmed byte order and verifies every
changed byte. It is intentionally a partial diagnostic probe, not a claimed fix.

Run from the repository root:
    python3 fm2008/dbpatch/patch_russian_roster_links_probe.py \
        --db fm2008/dbpatch/input --out fm2008/dbpatch/ready
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import struct
import sys
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from activate import find_record
from compare_roster_regions import ROSTER_DEFAULT, string_id_for_name
from hunt import lang_blob
from si_db import Container, DbError

TARGET_FILES = ("client_db.dat", "server_db.dat")
A5_MARKER = b"\x00\xA5\x00\x00"  # bytes at serialized TEAM ID + 4
TEAM_PLUS_54_DELTA = 12  # bytes at serialized TEAM ID + 12
EXPECTED_A5_IDS = 21
ZONE_COMPETITIONS = {
    "Запад": (130488, 179),
    "Центр": (130489, 180),
    "Юг": (130490, 181),
    "Восток": (130491, 182),
    "Урал-Поволжье": (8055759, 942),
}
DEFAULT_ARCHIVE = "fm2008-russian-roster-links-probe.zip"


@dataclass(frozen=True)
class Edit:
    team_id: int
    zone: str
    team_name: str
    comp_id: int
    comp_slot: int
    id_offset: int
    old: bytes
    new: bytes


def load_roster_ids(db: Path, roster_path: Path) -> dict[int, tuple[str, str]]:
    """Return exact lang_db team-ID -> (zone, CSV name), rejecting ambiguity."""
    text_blob = lang_blob(db)
    by_id: dict[int, tuple[str, str]] = {}
    with roster_path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            zone, name = row["zone"], row["full"]
            if zone not in ZONE_COMPETITIONS:
                raise DbError(f"unknown roster zone {zone!r}")
            match = string_id_for_name(text_blob, name)
            # Do not guess a team ID from a reserve-name fallback or fuzzy match.
            if match is None or match[1]:
                continue
            team_id = match[0]
            prior = by_id.get(team_id)
            candidate = (zone, name)
            if prior is not None and prior[0] != zone:
                raise DbError(
                    f"TEAM ID {team_id} appears in multiple zones: "
                    f"{prior[0]!r} and {zone!r}"
                )
            by_id.setdefault(team_id, candidate)
    if not by_id:
        raise DbError("no exact roster team IDs found in the Russian lang_db stream")
    return by_id


def find_a5_team_record(data: bytes, team_id: int) -> int | None:
    """Find the unique A5-shaped record for a TEAM ID; return its ID offset."""
    needle = struct.pack("<I", team_id)
    offsets: list[int] = []
    cursor = 0
    while True:
        pos = data.find(needle, cursor)
        if pos < 0:
            break
        cursor = pos + 1
        if pos + 20 > len(data) or data[pos + 4:pos + 8] != A5_MARKER:
            continue
        # A5 row prefix contains an ordinal immediately before the u32 ID.
        if pos < 4:
            continue
        ordinal = struct.unpack_from("<I", data, pos - 4)[0]
        if ordinal > 20_000:
            continue
        offsets.append(pos)
    if len(offsets) > 1:
        raise DbError(
            f"TEAM ID {team_id}: multiple A5-shaped rows at "
            + ", ".join(hex(x) for x in offsets)
        )
    return offsets[0] if offsets else None


def verify_comp_slots(data: bytes, filename: str) -> None:
    """Confirm the known target COMP IDs still occupy the expected manager slots."""
    for zone, (comp_id, expected_slot) in ZONE_COMPETITIONS.items():
        pos = find_record(data, comp_id)
        if pos is None:
            raise DbError(f"{filename}: target COMP {comp_id} ({zone}) not found")
        if pos < 4:
            raise DbError(f"{filename}: invalid ordinal position for COMP {comp_id}")
        actual_slot = struct.unpack_from("<I", data, pos - 4)[0]
        if actual_slot != expected_slot:
            raise DbError(
                f"{filename}: COMP {comp_id} expected slot {expected_slot}, "
                f"found {actual_slot}; refusing to patch this database version"
            )


def build_edits(data: bytes, filename: str, roster_ids: dict[int, tuple[str, str]]) -> list[Edit]:
    verify_comp_slots(data, filename)
    edits: list[Edit] = []
    for team_id, (zone, team_name) in sorted(roster_ids.items()):
        id_offset = find_a5_team_record(data, team_id)
        if id_offset is None:
            continue
        comp_id, comp_slot = ZONE_COMPETITIONS[zone]
        old = data[id_offset + TEAM_PLUS_54_DELTA:id_offset + TEAM_PLUS_54_DELTA + 4]
        # The resolver reads these four serialized bytes as a big-endian ordinal.
        new = comp_slot.to_bytes(4, "big")
        edits.append(Edit(team_id, zone, team_name, comp_id, comp_slot, id_offset, old, new))
    if len(edits) != EXPECTED_A5_IDS:
        raise DbError(
            f"{filename}: expected exactly {EXPECTED_A5_IDS} exact-name A5 TEAM rows, "
            f"found {len(edits)}; refusing a partial or mismatched-version patch"
        )
    return edits


def apply_edits(data: bytes, edits: list[Edit]) -> bytes:
    out = bytearray(data)
    seen: set[int] = set()
    for edit in edits:
        pos = edit.id_offset + TEAM_PLUS_54_DELTA
        if pos in seen:
            raise DbError(f"overlapping TEAM+0x54 edit at {pos:#x}")
        seen.add(pos)
        if data[pos:pos + 4] != edit.old:
            raise DbError(f"TEAM {edit.team_id}: source bytes changed at {pos:#x}")
        out[pos:pos + 4] = edit.new
    result = bytes(out)
    allowed = {edit.id_offset + TEAM_PLUS_54_DELTA + i for edit in edits for i in range(4)}
    changed = {i for i, (a, b) in enumerate(zip(data, result)) if a != b}
    if changed - allowed:
        raise DbError(f"unexpected changes outside the planned TEAM+0x54 fields: {sorted(changed - allowed)[:8]}")
    for edit in edits:
        pos = edit.id_offset + TEAM_PLUS_54_DELTA
        if result[pos:pos + 4] != edit.new:
            raise DbError(f"TEAM {edit.team_id}: output verification failed")
    return result


def build_probe(db: Path, roster_path: Path) -> tuple[dict[str, bytes], list[Edit]]:
    if not db.is_dir():
        raise DbError(f"database directory does not exist: {db}")
    if not roster_path.is_file():
        raise DbError(f"roster CSV does not exist: {roster_path}")
    roster_ids = load_roster_ids(db, roster_path)
    packed: dict[str, bytes] = {}
    file_edits: dict[str, list[Edit]] = {}
    for filename in TARGET_FILES:
        source = Container.load(db / filename)
        data = source.decompressed()
        edits = build_edits(data, filename, roster_ids)
        patched = apply_edits(data, edits)
        # Original, non-target bytes and the uncompressed table size must be preserved.
        if len(patched) != len(data):
            raise DbError(f"{filename}: uncompressed table size changed")
        packed[filename] = source.pack(patched)
        file_edits[filename] = edits

    signature = lambda row: (row.team_id, row.zone, row.comp_id, row.comp_slot, row.old, row.new)
    first = [signature(row) for row in file_edits[TARGET_FILES[0]]]
    second = [signature(row) for row in file_edits[TARGET_FILES[1]]]
    if first != second:
        raise DbError("client_db/server_db roster edit plans differ; refusing to package")
    return packed, file_edits[TARGET_FILES[0]]


def package_probe(db: Path, roster_path: Path, out_dir: Path) -> Path:
    packed, edits = build_probe(db, roster_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / DEFAULT_ARCHIVE
    if archive.exists():
        raise DbError(f"refusing to overwrite existing archive: {archive}")

    readme = [
        "FM2008 8.0.2 — Russian 2007 roster-link probe",
        "=" * 48,
        "",
        "This is a partial diagnostic probe, not a verified final fix.",
        "It rewrites only serialized TEAM+0x54 on exact-name A5-form team records",
        "found in both client_db.dat and server_db.dat. Each is assigned to the",
        "Russian zone COMP named in the repository's 2007 roster CSV.",
        "",
        "Scope: 21 A5-form TEAM records. Other CSV clubs, non-A5 TEAM records,",
        "league rules, flags, and fm.exe are not changed. The probe only targets",
        "the already-confirmed first roster gate; later virtual eligibility checks",
        "may still reject a team, and the game has not been run with this probe.",
        "",
        "Installation: use a COPY of the game's 8.0.2 database. Extract both .dat",
        "files into that copy, replacing only those copies. Clear the game cache and",
        "start a new game. Preserve the originals for rollback. Do not use on a",
        "different database revision. Roll back by restoring the two original files.",
        "",
        "Edits (TEAM ID; zone; COMP ID; confirmed COMP slot; old +0x54 bytes; new):",
    ]
    for row in edits:
        readme.append(
            f"{row.team_id}; {row.zone}; {row.comp_id}; {row.comp_slot}; "
            f"{row.old.hex(' ')}; {row.new.hex(' ')}"
        )
    sums = {name: hashlib.sha256(blob).hexdigest() for name, blob in packed.items()}
    readme.extend(["", "SHA256 of packed database files:"])
    readme.extend(f"{digest}  {name}" for name, digest in sums.items())

    with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED) as zf:
        for filename, blob in packed.items():
            zf.writestr(filename, blob)
        zf.writestr("PROBE_README.txt", "\n".join(readme) + "\n")
        zf.writestr(
            "SHA256SUMS.txt",
            "".join(f"{digest}  {name}\n" for name, digest in sums.items()),
        )
    # Verify archive contents by decompressing both files and re-running all plan checks.
    with zipfile.ZipFile(archive, "r") as zf:
        for filename in TARGET_FILES:
            unpacked = zf.read(filename)
            cont = Container.load(db / filename)
            out_data = Container(archive, unpacked[:9], unpacked[9:], True).decompressed()
            edits_for_file = build_edits(cont.decompressed(), filename, load_roster_ids(db, roster_path))
            expected = apply_edits(cont.decompressed(), edits_for_file)
            if out_data != expected:
                archive.unlink(missing_ok=True)
                raise DbError(f"{filename}: archived probe failed round-trip verification")
    return archive


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path, help="source 8.0.2 database directory")
    parser.add_argument("--roster", type=Path, default=ROSTER_DEFAULT)
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "ready")
    args = parser.parse_args()
    try:
        archive = package_probe(args.db, args.roster, args.out)
    except (DbError, OSError, struct.error, zipfile.BadZipFile) as exc:
        raise SystemExit(str(exc)) from exc
    print(f"probe archive: {archive} ({archive.stat().st_size:,} bytes)")
    with zipfile.ZipFile(archive, "r") as zf:
        for name in TARGET_FILES:
            print(f"SHA256 {name}: {hashlib.sha256(zf.read(name)).hexdigest()}")
        print(f"patched TEAM+0x54 records per DB: {EXPECTED_A5_IDS}")


if __name__ == "__main__":
    main()
