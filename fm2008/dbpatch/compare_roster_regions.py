#!/usr/bin/env python3
"""Сверить клубные региональные ссылки базы с CSV Второго дивизиона 2007 года.

Read-only диагностический скрипт. Он сопоставляет полную русскую строку
клуба с записью `lang_db`; если найдено только имя с `(Д)`, помечает его как
возможную резервную команду и не считает матчем первой команды. Для точного
имени выбирается правдоподобная английская запись того же ID; в `server_db`
проверяется типизированная пара
`03 <zone> 04 <lower group>` перед именем.

Это проверка корреляции, не декодер состава: часть имён CSV отсутствует в базе,
а найденная связь может описывать географию/путь перехода, а не участие клуба
в сезоне. Ни один файл базы не изменяется.

Запуск из корня репозитория:
    python3 fm2008/dbpatch/compare_roster_regions.py --db /path/to/db
"""
from __future__ import annotations

import argparse
import csv
import re
import struct
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

from hunt import lang_blob
from si_db import Container, zlib_streams

ZONE_IDS = {
    "Запад": 130488,
    "Центр": 130489,
    "Юг": 130490,
    "Восток": 130491,
    "Урал-Поволжье": 8055759,
}
ROSTER_DEFAULT = (
    Path(__file__).resolve().parents[2]
    / "fm2008/second-division-2007/data/second_division_2007.csv"
)


def string_id_for_name(text_blob: bytes, text: str) -> tuple[int, bool] | None:
    """Найти точную строку; отдельно пометить fallback на запись с `(Д)`."""
    raw = text.encode("utf-16-le")
    annotated_id: int | None = None
    pos = 0
    while True:
        pos = text_blob.find(raw, pos)
        if pos < 0:
            return (annotated_id, True) if annotated_id is not None else None
        if pos >= 8:
            string_id, length = struct.unpack_from("<II", text_blob, pos - 8)
            end = pos + length * 2
            if 1 <= length <= 160 and end + 2 <= len(text_blob):
                full = text_blob[pos:end].decode("utf-16-le", "replace")
                suffix = full[len(text):]
                is_reserve_variant = (
                    full.startswith(text)
                    and re.fullmatch(r" \(Д\)", suffix) is not None
                )
                if text_blob[end:end + 2] == b"\x00\x00":
                    if full == text:
                        return string_id, False
                    if is_reserve_variant and annotated_id is None:
                        annotated_id = string_id
        pos += 2


def normalized_name(text: str) -> str:
    """Упрощённая русско-латинская транслитерация для отсева чужих ID."""
    transliteration = str.maketrans({
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e",
        "ё": "e", "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k",
        "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
        "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
        "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "",
        "э": "e", "ю": "yu", "я": "ya",
    })
    ascii_text = unicodedata.normalize("NFKD", text.casefold().translate(transliteration))
    ascii_text = "".join(char for char in ascii_text if not unicodedata.combining(char))
    return " ".join("".join(char.lower() if char.isalnum() else " " for char in ascii_text).split())


def localized_name(
    streams: list[bytes], string_id: int, server: bytes, expected_name: str
) -> str | None:
    """Найти перевод ID в server_db, отсекая неоднозначные чужие строки по имени."""
    raw_id = struct.pack("<I", string_id)
    expected = normalized_name(expected_name)
    candidates: set[str] = set()
    # Поток 0 — английская локализация в этой версии lang_db. Ограничение
    # одним потоком также не смешивает одноимённые ID из других языков.
    for blob in streams[:1]:
        pos = 0
        while True:
            pos = blob.find(raw_id, pos)
            if pos < 0:
                break
            if pos + 8 <= len(blob):
                length = struct.unpack_from("<I", blob, pos + 4)[0]
                end = pos + 8 + length * 2
                if (
                    1 <= length <= 160
                    and end + 2 <= len(blob)
                    and blob[end:end + 2] == b"\x00\x00"
                ):
                    raw_text = blob[pos + 8:end]
                    text = raw_text.decode("utf-16-le", "replace")
                    if all(ord(char) >= 32 for char in text) and raw_text in server:
                        score = SequenceMatcher(
                            None, expected, normalized_name(text)
                        ).ratio()
                        if score == 1.0:
                            return text
                        candidates.add(text)
            pos += 1

    ranked = sorted(
        (
            SequenceMatcher(None, expected, normalized_name(candidate)).ratio(),
            candidate,
        )
        for candidate in candidates
    )
    if not ranked or ranked[-1][0] < 0.58:
        return None
    if len(ranked) > 1 and ranked[-1][0] == ranked[-2][0] and ranked[-1][1] != ranked[-2][1]:
        return None
    return ranked[-1][1]


def zone_links_before_name(server: bytes, name: str) -> set[tuple[int, int, int]]:
    """Собрать exact links, начинающиеся за 48/49 байт до UTF-16 имени."""
    raw_name = name.encode("utf-16-le")
    links: set[tuple[int, int, int]] = set()
    pos = 0
    while True:
        pos = server.find(raw_name, pos)
        if pos < 0:
            break
        end = pos + len(raw_name)
        # Не принимать имя как подстроку, например Dinamo Moscow (D).
        if server[end:end + 2] == b"\x00\x00":
            for gap in (48, 49):
                start = pos - gap
                if start < 0 or start + 10 > len(server):
                    continue
                if server[start] != 3 or server[start + 5] != 4:
                    continue
                zone_id = struct.unpack_from("<I", server, start + 1)[0]
                lower_id = struct.unpack_from("<I", server, start + 6)[0]
                if zone_id in ZONE_IDS.values():
                    links.add((zone_id, lower_id, start))
        pos += 2
    return links


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--roster", type=Path, default=ROSTER_DEFAULT)
    args = parser.parse_args()
    if not args.db.is_dir():
        raise SystemExit(f"нет папки базы {args.db}")
    if not args.roster.is_file():
        raise SystemExit(f"нет CSV состава {args.roster}")

    russian = lang_blob(args.db)
    streams = [data for _, data in zlib_streams((args.db / "lang_db.dat").read_bytes())]
    server = Container.load(args.db / "server_db.dat").decompressed()
    rows = csv.DictReader(args.roster.open(encoding="utf-8-sig", newline=""))
    counts: Counter[str] = Counter()

    print("zone; клуб CSV; ID; имя из базы; найденные пары (zone ID → lower ID); статус")
    for row in rows:
        expected_id = ZONE_IDS.get(row["zone"])
        name_match = string_id_for_name(russian, row["full"])
        if name_match is None:
            counts["no-id"] += 1
            print(f"{row['zone']}; {row['full']}; —; —; —; нет точной строки в lang_db")
            continue
        string_id, reserve_variant = name_match

        name = localized_name(streams, string_id, server, row["full"])
        if reserve_variant or (name is not None and name.endswith(" (D)")):
            counts["reserve-variant"] += 1
            print(
                f"{row['zone']}; {row['full']}; {string_id}; {name or '—'}; —; "
                "только вариант (Д), не считаю первой командой"
            )
            continue
        if name is None:
            counts["no-server-name"] += 1
            print(f"{row['zone']}; {row['full']}; {string_id}; —; —; нет имени в server_db")
            continue

        links = zone_links_before_name(server, name)
        zones = sorted({zone_id for zone_id, _, _ in links})
        if expected_id in zones:
            status = "совпадает"
            counts["expected-zone"] += 1
        elif zones:
            status = "другая зона"
            counts["other-zone"] += 1
        else:
            status = "пара не найдена"
            counts["no-link"] += 1
        counts["resolved"] += 1
        display = ", ".join(f"{zone_id}→{lower_id}" for zone_id, lower_id, _ in sorted(links)) or "—"
        print(f"{row['zone']}; {row['full']}; {string_id}; {name}; {display}; {status}")

    print("\nИтог:", ", ".join(f"{key}={value}" for key, value in sorted(counts.items())))
    print("Внимание: совпадение зоны не подтверждает текущую регистрацию клуба в лиге.")


if __name__ == "__main__":
    main()
