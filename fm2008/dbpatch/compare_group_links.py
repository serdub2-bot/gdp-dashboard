#!/usr/bin/env python3
"""Сравнить иерархические ID/записи Испании B и российских зон.

Скрипт не изменяет файлы. Он выводит:
* маркеры, уровни и поля +36/+40 родительских ID 121091, 126964 и 8051008;
* те же поля записей групп Испании, Португалии и России;
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
PORTUGAL_PARENT = 126_964
RUSSIAN_PARENT = 8_051_008
SPECIAL_MARKER = bytes.fromhex("00 00 00 90 00 c5 6e ff 01")
PORTUGAL_PARENT_MARKER = bytes.fromhex("00 00 00 5a 01 c0 7f 5a 01")
SPAIN_B4_MARKER = bytes.fromhex("00 00 00 ff 7f c5 6e c5 6e")
PORTUGAL_GROUP_MARKER = bytes.fromhex("00 00 00 06 02 00 70 06 02")
SPECIAL_GROUP_MARKERS = {
    62: PORTUGAL_GROUP_MARKER,
    63: PORTUGAL_GROUP_MARKER,
    64: PORTUGAL_GROUP_MARKER,
    72: SPAIN_B4_MARKER,
}
GROUPS = {
    62: "Portugal B North",
    63: "Portugal B Central",
    64: "Portugal B South",
    67: "Spain First Division (control)",
    68: "Spain Second Division (control)",
    69: "Spain B1",
    70: "Spain B2",
    71: "Spain B3",
    72: "Spain B4",
    130487: "Russia First Division (control)",
    130488: "Russia West",
    130489: "Russia Center",
    130490: "Russia South",
    130491: "Russia East",
    8055759: "Russia Ural/Volga",
}


def locate_parent(data: bytes, comp_id: int) -> tuple[int, bytes] | None:
    """Найти ID по обычному либо известным альтернативным маркерам записи."""
    raw_id = struct.pack("<I", comp_id)
    pos = data.find(raw_id)
    while pos >= 0:
        marker = data[pos + 4:pos + 13]
        if marker in {SPECIAL_MARKER, PORTUGAL_PARENT_MARKER} or find_record(data, comp_id) == pos:
            return pos, marker
        pos = data.find(raw_id, pos + 1)
    return None


def locate_marker(data: bytes, comp_id: int, markers: set[bytes]) -> tuple[int, bytes] | None:
    raw_id = struct.pack("<I", comp_id)
    pos = data.find(raw_id)
    while pos >= 0:
        marker = data[pos + 4:pos + 13]
        if marker in markers:
            return pos, marker
        pos = data.find(raw_id, pos + 1)
    return None


def name_map(db: Path) -> dict[int, str]:
    return {row["id"]: row["name"] for row in list_competitions(lang_blob(db), "")}


def nearby_utf16_text(data: bytes, pos: int, span: int = 220) -> str | None:
    """Первый печатный UTF-16LE-фрагмент после пары; только подсказка для анализа."""
    end = min(len(data), pos + span)
    for start in range(pos + 9, end - 1, 2):
        chars: list[str] = []
        cursor = start
        while cursor + 1 < end:
            codepoint = data[cursor] | (data[cursor + 1] << 8)
            if codepoint == 0:
                break
            if not (32 <= codepoint <= 126 or 0x400 <= codepoint <= 0x52F
                    or codepoint in (0x2013, 0x2019, 0x2014)):
                break
            chars.append(chr(codepoint))
            cursor += 2
        text = "".join(chars).strip()
        if len(text) >= 8 and sum(char.isalpha() for char in text) >= 5:
            return text
    return None


def group_links(data: bytes, group_id: int) -> list[tuple[int, int, str | None]]:
    """Find `03 <group> 04 <competition>` pairs and nearby club-name hints."""
    pattern = b"\x03" + struct.pack("<I", group_id) + b"\x04"
    found: list[tuple[int, int, str | None]] = []
    pos = 0
    while True:
        pos = data.find(pattern, pos)
        if pos < 0:
            return found
        if pos + 10 <= len(data):
            related_id = struct.unpack_from("<I", data, pos + 6)[0]
            found.append((pos, related_id, nearby_utf16_text(data, pos)))
        pos += 1


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
    for comp_id in (SPECIAL_PARENT, PORTUGAL_PARENT, RUSSIAN_PARENT):
        row = locate_parent(client, comp_id)
        if row is None:
            print(f"  {comp_id}: нет записи")
            continue
        pos, marker = row
        p1, p2 = struct.unpack_from("<II", client, pos + 36)
        row_index = struct.unpack_from("<I", client, pos - 4)[0]
        print(f"  {comp_id} {names.get(comp_id, '')}: marker={marker.hex(' ')} "
              f"level={client[pos + 23]} row={row_index} +36/+40={p1}/{p2}")

    print("\nДочерние DB-записи:")
    for comp_id, label in GROUPS.items():
        pos = find_record(client, comp_id)
        marker = None
        if pos is None and comp_id in SPECIAL_GROUP_MARKERS:
            special_row = locate_marker(client, comp_id, {SPECIAL_GROUP_MARKERS[comp_id]})
            if special_row is not None:
                pos, marker = special_row
        if pos is None:
            print(f"  {label:<18} id={comp_id:<9} row=не распознана")
            continue
        if marker is None:
            marker = client[pos + 4:pos + 13]
        row_index = struct.unpack_from("<I", client, pos - 4)[0]
        p1, p2 = struct.unpack_from("<II", client, pos + 36)
        print(f"  {label:<32} id={comp_id:<9} level={client[pos + 23]} "
              f"row={row_index} +36/+40={p1}/{p2} marker={marker.hex(' ')}")

    print("\nЧастоты связей server_db: 03 <group ID> 04 <related ID>")
    for comp_id, label in GROUPS.items():
        links = group_links(server, comp_id)
        counts: Counter[int] = Counter(related for _, related, _ in links)
        readable_names = {hint for _, _, hint in links if hint}
        readable_hits = sum(hint is not None for _, _, hint in links)
        related = ", ".join(
            f"{other} ({names.get(other, 'без строки')}) ×{count}"
            for other, count in counts.most_common(8)
        )
        print(f"  {label:<18} matches={sum(counts.values()):<4} "
              f"name-hints={readable_hits}/{len(readable_names)} unique "
              f"{related or 'нет'}")

    print("\nПримеры: текст рядом с отдельными связями (эвристическая подсказка):")
    examples = ((130488, 8050940), (130490, 8050903), (130489, 8050900))
    for group_id, related_id in examples:
        pattern = (b"\x03" + struct.pack("<I", group_id) + b"\x04"
                   + struct.pack("<I", related_id))
        pos = 0
        while True:
            pos = server.find(pattern, pos)
            if pos < 0:
                print(f"  {group_id} -> {related_id}: нет")
                break
            text = nearby_utf16_text(server, pos)
            if text:
                print(f"  {group_id} -> {related_id}: рядом «{text}» (offset={pos})")
                break
            pos += 1


if __name__ == "__main__":

    main()
