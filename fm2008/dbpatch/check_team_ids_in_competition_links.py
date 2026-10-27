#!/usr/bin/env python3
"""Check whether known club IDs occupy typed competition-link fields.

Read-only probe of the `03 <ID> 04 <ID>` byte pattern in `server_db.dat`.
The IDs come from exact club-name records in the 2007 Second Division roster,
plus the parent/reserve IDs in the existing `(D)` analysis. A match would only
show that an ID appears in this link family; it would not by itself prove league
membership or the meaning of a field.

Usage:
    python3 fm2008/dbpatch/check_team_ids_in_competition_links.py --db /path/to/db
"""
from __future__ import annotations

import argparse
import csv
import struct
from pathlib import Path

from compare_reserve_links import reserve_link_rows
from compare_roster_regions import ROSTER_DEFAULT, string_id_for_name
from hunt import lang_blob
from si_db import Container, zlib_streams


def link_role_positions(data: bytes, entity_id: int) -> tuple[list[int], list[int]]:
    """Return offsets where ID is the `03` endpoint or `04` endpoint."""
    raw = struct.pack("<I", entity_id)
    as_03: list[int] = []
    pattern_03 = b"\x03" + raw + b"\x04"
    pos = 0
    while (pos := data.find(pattern_03, pos)) >= 0:
        as_03.append(pos)
        pos += 1

    as_04: list[int] = []
    pattern_04 = b"\x04" + raw
    pos = 0
    while (pos := data.find(pattern_04, pos)) >= 0:
        if pos >= 5 and data[pos - 5] == 0x03:
            as_04.append(pos - 5)
        pos += 1
    return as_03, as_04


def collect_ids(
    db: Path, roster_path: Path, server: bytes
) -> tuple[dict[int, set[str]], int, int]:
    """Build the set of club IDs from the roster and parent/(D) name pairs."""
    russian = lang_blob(db)
    lang_data = (db / "lang_db.dat").read_bytes()
    streams = [data for _, data in zlib_streams(lang_data)]
    if not streams:
        raise SystemExit("в lang_db.dat не найдены языковые потоки")
    english = streams[0]

    id_names: dict[int, set[str]] = {}
    roster_ids: set[int] = set()
    with roster_path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            match = string_id_for_name(russian, row["full"])
            if match is None or match[1]:
                continue
            entity_id = match[0]
            roster_ids.add(entity_id)
            id_names.setdefault(entity_id, set()).add(row["full"])

    _, linked_reserves = reserve_link_rows(english, server)
    reserve_ids: set[int] = set()
    for reserve_name, _, _ in linked_reserves:
        for name in (reserve_name[:-4], reserve_name):
            match = string_id_for_name(english, name)
            if match is None or match[1]:
                continue
            entity_id = match[0]
            reserve_ids.add(entity_id)
            id_names.setdefault(entity_id, set()).add(name)

    return id_names, len(roster_ids), len(reserve_ids)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--roster", type=Path, default=ROSTER_DEFAULT)
    args = parser.parse_args()
    if not args.db.is_dir():
        raise SystemExit(f"нет папки базы {args.db}")
    if not args.roster.is_file():
        raise SystemExit(f"нет CSV ростера {args.roster}")

    server = Container.load(args.db / "server_db.dat").decompressed()
    id_names, roster_count, reserve_count = collect_ids(args.db, args.roster, server)
    ids = set(id_names) - {0}
    as_03_total = as_04_total = 0
    print(f"точные ID клубов из CSV Второго дивизиона: {roster_count}")
    print(f"ID родителей/резервов из связанных `(D)`-записей: {reserve_count}")
    print(f"уникальных ID в объединении: {len(ids)}")
    for entity_id in sorted(ids):
        as_03, as_04 = link_role_positions(server, entity_id)
        as_03_total += len(as_03)
        as_04_total += len(as_04)
        if as_03 or as_04:
            names = ", ".join(sorted(id_names[entity_id]))
            print(f"  ID={entity_id} names={names!r} as-03={as_03} as-04={as_04}")
    print(f"team IDs found as `03` competition endpoint: {as_03_total}")
    print(f"team IDs found as `04` competition endpoint: {as_04_total}")
    print("Ноль совпадений относится только к полям `03/04`; это не доказывает, "
          "что клубные ID нигде больше не используются для регистрации.")


if __name__ == "__main__":
    main()
