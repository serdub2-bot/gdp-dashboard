#!/usr/bin/env python3
"""Сравнить иерархические ID/записи Испании B и российских зон.

Скрипт не изменяет файлы. Он выводит:
* маркер и поле уровня для родительских ID 121091 и 8051008;
* уровни обычных записей дочерних групп;
* частоты бинарных связей вида `03 <u32 group_id> 04 <u32 related_comp_id>`
  в server_db.dat и названия связанных ID, если они есть в русской таблице строк.

Смысл пары 03/04 пока не расшифрован окончательно; выводить её как текущий
состав клуба или как таблицу повышений/понижений без дополнительных проверок
нельзя.

Запуск:
    python3 compare_group_links.py --db /path/to/FM2008/data/db
"""
from __future__ import annotations

import argparse
import struct
from collections import Counter
from pathlib import Path

from activate import find_record
from hunt import lang_blob, list_competitions
from si_db import Container

SPECIAL_PARENT = 121_091
RUSSIAN_PARENT = 8_051_008
SPECIAL_MARKER = bytes.fromhex("00 00 00 90 00 c5 6e ff 01")
GROUPS = {
    69: "Spain B1",
    70: "Spain B2",
    71: "Spain B3",
    72: "Spain B4",
    130488: "Russia West",
    130489: "Russia Center",
    130490: "Russia South",
    130491: "Russia East",
    8055759: "Russia Ural/Volga",
}


def locate_parent(data: bytes, comp_id: int) -> tuple[int, bytes] | None:
    """Найти ID; распознать standard marker либо испанский special marker."""
    raw_id = struct.pack("<I", comp_id)
    pos = data.find(raw_id)
    while pos >= 0:
        marker = data[pos + 4:pos + 13]
        if marker == SPECIAL_MARKER or find_record(data, comp_id) == pos:
            return pos, marker
        pos = data.find(raw_id, pos + 1)
    return None


def name_map(db: Path) -> dict[int, str]:
    return {row["id"]: row["name"] for row in list_competitions(lang_blob(db), "")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    args = parser.parse_args()
    if not args.db.is_dir():
        raise SystemExit(f"нет папки {args.db}")

    client = Container.load(args.db / "client_db.dat").decompressed()
    server = Container.load(args.db / "server_db.dat").decompressed()
    names = name_map(args.db)

    print("Родительские записи (поле уровня: +23 от ID):")
    for comp_id in (SPECIAL_PARENT, RUSSIAN_PARENT):
        row = locate_parent(client, comp_id)
        if row is None:
            print(f"  {comp_id}: нет записи")
            continue
        pos, marker = row
        print(f"  {comp_id} {names.get(comp_id, '')}: marker={marker.hex(' ')} "
              f"level={client[pos + 23]} offset={pos}")

    print("\nДочерние DB-записи:")
    for comp_id, label in GROUPS.items():
        pos = find_record(client, comp_id)
        if pos is None:
            print(f"  {label:<18} id={comp_id:<9} standard-row=нет")
        else:
            print(f"  {label:<18} id={comp_id:<9} level={client[pos + 23]}")

    print("\nЧастоты связей server_db: 03 <group ID> 04 <related ID>")
    for comp_id, label in GROUPS.items():
        pattern = b"\x03" + struct.pack("<I", comp_id) + b"\x04"
        counts: Counter[int] = Counter()
        pos = 0
        while True:
            pos = server.find(pattern, pos)
            if pos < 0:
                break
            if pos + 10 <= len(server):
                related_id = struct.unpack_from("<I", server, pos + 6)[0]
                counts[related_id] += 1
            pos += 1
        related = ", ".join(
            f"{other} ({names.get(other, 'без строки')}) ×{count}"
            for other, count in counts.most_common(8)
        )
        print(f"  {label:<18} matches={sum(counts.values()):<4} {related or 'нет'}")


if __name__ == "__main__":
    main()
