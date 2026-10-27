#!/usr/bin/env python3
"""Проверить связи основных клубов с вариантами `(D)` в FM2008.

Read-only диагностика: находит записи английского потока `lang_db`, оканчивающиеся
на `(D)`, и проверяет пары `03 <zone> 04 <lower competition>` перед именем
основного клуба и перед самим вариантом `(D)`. Это позволяет воспроизвести
проверку гипотезы о лигах резервных команд; пары не трактуются как точный список
участников или как доказанная регистрация дубля.

Запуск:
    python3 fm2008/dbpatch/compare_reserve_links.py --db /path/to/db
"""
from __future__ import annotations

import argparse
import struct
from pathlib import Path

from compare_roster_regions import zone_links_before_name
from hunt import lang_blob, list_competitions
from si_db import Container, zlib_streams

SUFFIX = " (D)"
MAX_NAME_LENGTH = 160
COMPETITION_NAME_FALLBACKS = {
    8_055_759: "Россия. Второй дивизион - Урал/Волга",
}


def names_with_suffix(blob: bytes, suffix: str = SUFFIX) -> set[str]:
    """Вытащить полные UTF-16LE записи, заканчивающиеся заданным суффиксом."""
    raw_suffix = suffix.encode("utf-16-le")
    suffix_chars = len(suffix)
    names: set[str] = set()
    pos = 0
    while True:
        pos = blob.find(raw_suffix, pos)
        if pos < 0:
            return names
        for length in range(suffix_chars, MAX_NAME_LENGTH + 1):
            start = pos - 2 * (length - suffix_chars)
            end = start + 2 * length
            if start < 8 or end + 2 > len(blob):
                continue
            record_length = struct.unpack_from("<I", blob, start - 4)[0]
            if record_length != length or blob[end:end + 2] != b"\x00\x00":
                continue
            try:
                name = blob[start:end].decode("utf-16-le")
            except UnicodeDecodeError:
                continue
            if name.endswith(suffix) and all(ord(char) >= 32 for char in name):
                names.add(name)
        pos += 2


def reserve_link_rows(
    english_blob: bytes, server: bytes
) -> tuple[set[str], list[tuple[str, set[tuple[int, int, int]], set[tuple[int, int, int]]]]]:
    """Вернуть все `(D)`-имена и строки, у которых есть parent- или D-link."""
    reserve_names = names_with_suffix(english_blob)
    linked = []
    for reserve_name in sorted(reserve_names, key=str.casefold):
        parent_name = reserve_name[:-len(SUFFIX)]
        parent_links = zone_links_before_name(server, parent_name)
        reserve_links = zone_links_before_name(server, reserve_name)
        if parent_links or reserve_links:
            linked.append((reserve_name, parent_links, reserve_links))
    return reserve_names, linked


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    args = parser.parse_args()
    if not args.db.is_dir():
        raise SystemExit(f"нет папки базы {args.db}")

    lang_data = (args.db / "lang_db.dat").read_bytes()
    streams = [data for _, data in zlib_streams(lang_data)]
    if not streams:
        raise SystemExit("в lang_db.dat не найдены языковые потоки")
    russian_names = {
        row["id"]: row["name"] for row in list_competitions(lang_blob(args.db), "Россия")
    }
    server = Container.load(args.db / "server_db.dat").decompressed()
    reserves, linked = reserve_link_rows(streams[0], server)
    parent_count = sum(bool(parent) for _, parent, _ in linked)
    direct_count = sum(bool(direct) for _, _, direct in linked)

    print(f"уникальных полных имён `(D)` в английском потоке: {len(reserves)}")
    print(f"ссылок перед основным именем: {parent_count}")
    print(f"ссылок перед именем `(D)`: {direct_count}")
    print("вариант `(D)`; пары у основного имени; пары у `(D)`")
    for reserve_name, parent_links, reserve_links in linked:
        def title(comp_id: int) -> str:
            return russian_names.get(
                comp_id,
                COMPETITION_NAME_FALLBACKS.get(comp_id, "без названия"),
            )

        def display(links: set[tuple[int, int, int]]) -> str:
            return ", ".join(
                f"{zone} ({title(zone)}) → {lower} ({title(lower)})"
                for zone, lower, _ in sorted(links)
            ) or "—"

        print(f"{reserve_name}; {display(parent_links)}; {display(reserve_links)}")


if __name__ == "__main__":
    main()
