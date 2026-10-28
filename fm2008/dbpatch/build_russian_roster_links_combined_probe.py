#!/usr/bin/env python3
"""Build a controlled roster-link probe on the previously tested flag-4 baseline.

The existing flag-4 parent-registration executable is copied unchanged from its
archive. The only new game-data edits are 21 checked TEAM+0x54 words in each DB.
The archive is standalone, but remains a diagnostic probe rather than a proven fix.
"""
from __future__ import annotations

import argparse
import hashlib
import zipfile
from pathlib import Path

import build_flag4_parent_probe as parent_probe
import patch_exe
from compare_roster_regions import ROSTER_DEFAULT
from patch_russian_roster_links_probe import (
    EXPECTED_A5_IDS,
    TARGET_FILES,
    apply_edits,
    build_edits,
    load_roster_ids,
)
from si_db import Container, DbError

ARCHIVE_NAME = "fm2008-russian-roster-links-parent-flag4-probe.zip"
DEFAULT_EXE_ARCHIVE = (
    Path(__file__).resolve().parent
    / "ready"
    / "fm2008-second-division-flag4-parent-probe.zip"
)


def read_validated_exe(archive_path: Path) -> bytes:
    if not archive_path.is_file():
        raise DbError(f"missing validated baseline archive: {archive_path}")
    with zipfile.ZipFile(archive_path, "r") as zf:
        if zf.testzip() is not None or zf.namelist().count("fm.exe") != 1:
            raise DbError("baseline archive failed CRC check or lacks exactly one fm.exe")
        exe = zf.read("fm.exe")

    expected_hook = patch_exe.jmp_rel(patch_exe.HOOK_VA, patch_exe.STUB_VA)
    expected_stub = parent_probe.build_stub()
    if (
        exe[patch_exe.HOOK_RAW:patch_exe.HOOK_RAW + 5] != expected_hook
        or exe[patch_exe.STUB_RAW:patch_exe.STUB_RAW + len(expected_stub)] != expected_stub
        or exe[patch_exe.STUB_RAW + len(expected_stub):
              patch_exe.STUB_RAW + patch_exe.STUB_SPACE]
        != b"\x90" * (patch_exe.STUB_SPACE - len(expected_stub))
    ):
        raise DbError("baseline fm.exe is not the exact flag-4 parent probe")
    return exe


def build_payloads(
    exe_archive: Path, db: Path, roster_path: Path
) -> tuple[dict[str, bytes], list]:
    if not db.is_dir() or not roster_path.is_file():
        raise DbError("missing --db or roster CSV")

    payloads = {"fm.exe": read_validated_exe(exe_archive)}
    roster_ids = load_roster_ids(db, roster_path)
    edits_by_file: dict[str, list] = {}
    for filename in TARGET_FILES:
        container = Container.load(db / filename)
        before = container.decompressed()
        edits = build_edits(before, filename, roster_ids)
        after = apply_edits(before, edits)

        allowed = {
            edit.id_offset + 12 + byte_index
            for edit in edits for byte_index in range(4)
        }
        changed = {i for i, (old, new) in enumerate(zip(before, after)) if old != new}
        if changed - allowed:
            raise DbError(
                f"{filename}: unexpected byte changes outside TEAM+0x54: "
                f"{sorted(changed - allowed)[:8]}"
            )
        if len(after) != len(before):
            raise DbError(f"{filename}: uncompressed table size changed")
        packed = container.pack(after)
        roundtrip = Container(container.path, packed[:9], packed[9:], True).decompressed()
        if roundtrip != after:
            raise DbError(f"{filename}: packed database failed round-trip verification")
        payloads[f"data/db/802/{filename}"] = packed
        edits_by_file[filename] = edits

    signature = lambda row: (
        row.team_id, row.zone, row.comp_id, row.comp_slot, row.old, row.new
    )
    if [signature(row) for row in edits_by_file[TARGET_FILES[0]]] != [
        signature(row) for row in edits_by_file[TARGET_FILES[1]]
    ]:
        raise DbError("client_db/server_db TEAM edit plans differ")
    if len(edits_by_file[TARGET_FILES[0]]) != EXPECTED_A5_IDS:
        raise DbError("unexpected number of exact A5-form roster TEAM rows")
    return payloads, edits_by_file[TARGET_FILES[0]]


def build_archive(
    exe_archive: Path, db: Path, roster_path: Path, out_dir: Path
) -> Path:
    payloads, edits = build_payloads(exe_archive, db, roster_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / ARCHIVE_NAME
    if archive.exists():
        raise DbError(f"refusing to overwrite existing archive: {archive}")

    sums = {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()}
    readme = [
        "FM2008 8.0.2 — Russian roster-link probe on flag-4 parent baseline",
        "=" * 68,
        "",
        "This is a controlled diagnostic probe, not a confirmed playable fix.",
        "The included fm.exe is copied byte-for-byte from the existing flag-4",
        "parent-registration probe (8051008 / tier 2 / flag 4). That baseline was",
        "tested in-game: Russia and its five zone names appeared, but clubs did not.",
        "This package changes only TEAM+0x54 for 21 exact-name A5-form roster rows",
        "in both DB files; it does not alter COMP levels, zone parameters, rules,",
        "registration code, or other TEAM formats. The intent is to test whether",
        "these serialized roster-to-COMP links affect team loading on that baseline.",
        "",
        "Scope limits: exact A5 rows were found for only 21 of 44 resolved roster IDs.",
        "The other 23 resolved IDs (and roster names without exact DB IDs) are left",
        "unchanged. The field assignment is a probe, not proof that this alone controls",
        "eligibility. No game run with this combined package has confirmed an outcome.",
        "Spain B and Norway are comparison cases for grouped competition structure,",
        "not evidence that Russian eligibility uses an identical DB rule.",
        "",
        "Install only into a COPY of FM2008 8.0.2. Back up fm.exe and both DB files.",
        "Extract with paths preserved, clear the cache, and start a NEW game.",
        "Rollback by restoring the three original files. Do not use on other versions.",
        "",
        "TEAM edits (ID; zone; COMP ID; slot; old +0x54 bytes; new bytes):",
    ]
    for row in edits:
        readme.append(
            f"{row.team_id}; {row.zone}; {row.comp_id}; {row.comp_slot}; "
            f"{row.old.hex(' ')}; {row.new.hex(' ')}"
        )
    readme.extend(["", "SHA256:"])
    readme.extend(f"{digest}  {name}" for name, digest in sums.items())

    with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED) as zf:
        for name, data in payloads.items():
            zf.writestr(name, data)
        zf.writestr("PROBE_README.txt", "\n".join(readme) + "\n")
        zf.writestr(
            "SHA256SUMS.txt",
            "".join(f"{digest}  {name}\n" for name, digest in sums.items()),
        )

    try:
        with zipfile.ZipFile(archive, "r") as zf:
            if zf.namelist().count("fm.exe") != 1 or zf.testzip() is not None:
                raise DbError("archive entry count or CRC check failed")
            for name, expected in sums.items():
                if hashlib.sha256(zf.read(name)).hexdigest() != expected:
                    raise DbError(f"archive hash mismatch for {name}")
    except Exception:
        archive.unlink(missing_ok=True)
        raise
    return archive


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe-archive", type=Path, default=DEFAULT_EXE_ARCHIVE)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--roster", type=Path, default=ROSTER_DEFAULT)
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "ready")
    args = parser.parse_args()
    try:
        archive = build_archive(args.exe_archive, args.db, args.roster, args.out)
    except (DbError, OSError, zipfile.BadZipFile) as exc:
        raise SystemExit(str(exc)) from exc
    print(f"combined probe: {archive} ({archive.stat().st_size:,} bytes)")
    with zipfile.ZipFile(archive, "r") as zf:
        for name in ("fm.exe", "data/db/802/client_db.dat", "data/db/802/server_db.dat"):
            print(f"SHA256 {name}: {hashlib.sha256(zf.read(name)).hexdigest()}")
    print(f"TEAM+0x54 roster links patched in each DB: {EXPECTED_A5_IDS}")


if __name__ == "__main__":
    main()
