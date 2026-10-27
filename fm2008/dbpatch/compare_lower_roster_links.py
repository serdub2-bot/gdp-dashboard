#!/usr/bin/env python3
"""Сверить ссылки клубов Второго дивизиона с ростером Третьей лиги 2007.

Для каждой распознанной записи клуба берутся ID из пары `03/04`. По ID `04`
выбирается регион третьего дивизиона, затем ищутся команды того же города в
CSV-ростере. Отдельно отмечается совпадение названия клуба с вероятной командой
`-2`/дублем. Это географическая сверка, а не доказательство регистрации.

Запуск:
    python3 fm2008/dbpatch/compare_lower_roster_links.py --db /path/to/db
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

from compare_roster_regions import (
    localized_name,
    normalized_name,
    string_id_for_name,
    zone_links_before_name,
)
from hunt import lang_blob
from si_db import Container, zlib_streams

SECOND_ROSTER = (
    Path(__file__).resolve().parents[2]
    / "fm2008/second-division-2007/data/second_division_2007.csv"
)
THIRD_ROSTER = (
    Path(__file__).resolve().parents[2]
    / "fm2008/third-league-russia/data/clubs_2007.csv"
)
# ID 8050900 is «Центральная группа 1»; в используемом CSV нет отдельной
# зоны с таким названием, поэтому он намеренно не приравнивается к Черноземью.
LOWER_ID_TO_ZONE = {
    8050901: "Золотое кольцо",
    8050902: "Северо-Запад",
    8050903: "ЮФО",
    8050904: "Приволжье",
    8050905: "Дальний Восток",
    8050906: "Сибирь",
    8050907: "Урал и Западная Сибирь",
    8050908: "Черноземье",
    8050940: "Москва",
}


def name_prefix_match(first_team: str, lower_team: str) -> bool:
    """Консервативно сопоставить клубные основы после транслитерации."""
    base = normalized_name(first_team)
    candidate = normalized_name(lower_team)
    return bool(base) and (candidate == base or candidate.startswith(base + " "))


def local_candidates(
    roster_row: dict[str, str],
    links: set[tuple[int, int, int]],
    lower_rows: list[dict[str, str]],
) -> tuple[set[str], set[str]]:
    """Команды того же города и linked-зоны; отдельно — совпавшие основы."""
    zones = {
        LOWER_ID_TO_ZONE[lower_id]
        for _, lower_id, _ in links
        if lower_id in LOWER_ID_TO_ZONE
    }
    local = {
        row["club"]
        for row in lower_rows
        if row["status"] == "участник"
        and row["city"].casefold() == roster_row["city"].casefold()
        and row["zone"] in zones
    }
    same_club = {
        name for name in local if name_prefix_match(roster_row["club"], name)
    }
    return local, same_club


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--second-roster", type=Path, default=SECOND_ROSTER)
    parser.add_argument("--third-roster", type=Path, default=THIRD_ROSTER)
    args = parser.parse_args()
    if not args.db.is_dir():
        raise SystemExit(f"нет папки базы {args.db}")
    if not args.second_roster.is_file() or not args.third_roster.is_file():
        raise SystemExit("нет одного из CSV-ростеров")

    russian = lang_blob(args.db)
    streams = [data for _, data in zlib_streams((args.db / "lang_db.dat").read_bytes())]
    server = Container.load(args.db / "server_db.dat").decompressed()
    with args.second_roster.open(encoding="utf-8-sig", newline="") as handle:
        second_rows = list(csv.DictReader(handle))
    with args.third_roster.open(encoding="utf-8-sig", newline="") as handle:
        lower_rows = list(csv.DictReader(handle))

    counts: Counter[str] = Counter()
    print("zone; клуб; группа 04; записи третьей лиги в том же городе/зоне; вывод")
    for row in second_rows:
        id_match = string_id_for_name(russian, row["full"])
        if id_match is None:
            counts["unmapped-name"] += 1
            continue
        string_id, reserve_variant = id_match
        name = localized_name(streams, string_id, server, row["full"])
        if reserve_variant or (name is not None and name.endswith(" (D)")):
            counts["reserve-variant"] += 1
            continue
        if name is None:
            counts["unmapped-english"] += 1
            continue

        links = zone_links_before_name(server, name)
        if not links:
            counts["no-03-04-link"] += 1
            continue
        counts["linked-club"] += 1
        local, same_club = local_candidates(row, links, lower_rows)
        if local:
            counts["same-city-and-zone"] += 1
        if same_club:
            counts["same-club-name"] += 1
            result = "вероятный резерв: " + ", ".join(sorted(same_club))
        elif local:
            counts["regional-only"] += 1
            result = "только другие местные команды: " + ", ".join(sorted(local))
        else:
            counts["no-local-roster-row"] += 1
            result = "нет записи того же города/зоны"
        lower_ids = ", ".join(str(lower) for _, lower, _ in sorted(links))
        print(
            f"{row['zone']}; {row['full']}; {lower_ids}; "
            f"{', '.join(sorted(local)) or '—'}; {result}"
        )

    print("\nИтог:", ", ".join(
        f"{key}={value}" for key, value in sorted(counts.items())
    ))
    print("Совпадение названия/города — эвристика, не подтверждённое членство.")


if __name__ == "__main__":
    main()
