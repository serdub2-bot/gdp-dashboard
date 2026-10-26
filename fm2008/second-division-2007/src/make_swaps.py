#!/usr/bin/env python3
"""Сборка .edt: перенос клубов Второго дивизиона в играбельный Первый.

В FM2008 активировать третий уровень нельзя (нет ни Add/Remove Leagues, ни
«Add nation rules» в редакторе — это появилось в FM2010). Рабочий способ сделать
клубы Второго дивизиона играбельными — поменять их местами с клубами Первого
дивизиона командой "SWAP_TEAMS". В Первом дивизионе 22 места, поэтому за один
файл поднимается одна зона (11–16 клубов).

Использование:
    python3 src/make_swaps.py                      # все зоны
    python3 src/make_swaps.py --zone Запад         # одна зона
    python3 src/make_swaps.py --lang-db /путь/lang_db.dat   # + сверка имён
    python3 src/make_swaps.py --boost              # добавить BOOST_TEAM (деньги/репутация)

Результат:
    edt/second_division_<зона>.edt   — файл для <игра>/data/db/
    data/swap_report.md              — что подтверждено базой, а что проверить
"""
from __future__ import annotations

import argparse
import csv
import re
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
EDT = ROOT / "edt"

EDT_RUS = {
    "Юг": "yug", "Запад": "zapad", "Центр": "centr",
    "Урал-Поволжье": "ural-povolzhye", "Восток": "vostok",
}


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def ru_strings(lang_db: Path) -> str:
    """Русская таблица строк из lang_db.dat (декодированный текст)."""
    blob = lang_db.read_bytes()
    best = ""
    i = 0
    while True:
        j = blob.find(b"\x78\x9c", i)
        if j < 0:
            break
        i = j + 1
        try:
            buf = zlib.decompressobj().decompress(blob[j:])
        except zlib.error:
            continue
        if len(buf) < 50_000:
            continue
        text = buf.decode("utf-16-le", errors="ignore")
        if len(re.findall(r"[А-ЯЁа-яё]{3,}", text)) > len(re.findall(r"[А-ЯЁа-яё]{3,}", best)):
            best = text
    return best


def base_name(club: str) -> str:
    """«Балтика-2» -> «балтика», «Краснодар-2000» -> «краснодар»."""
    name = re.sub(r"[-\s]?(\d+|д|дубль|мол\.?)$", "", club.strip().lower())
    return name


def related(a: dict, b: dict) -> bool:
    """Резерв и основа одного клуба — такую пару в SWAP_TEAMS не ставим."""
    return a["city"].lower() == b["city"].lower() and base_name(a["club"]) == base_name(b["club"])


def pair_up(zclubs: list[dict], first: list[dict]) -> list[tuple[dict, dict]]:
    """Жадно подбираем пары так, чтобы не свапать клуб с его же резервом."""
    pool = list(first)
    pairs: list[tuple[dict, dict]] = []
    for a in zclubs:
        idx = next((i for i, b in enumerate(pool) if not related(a, b)), None)
        if idx is None:
            raise SystemExit(f"не осталось подходящей пары для «{a['full']}»")
        pairs.append((a, pool.pop(idx)))
    return pairs


def confidence(club: str, city: str, text: str | None) -> str:
    if text is None:
        return "не проверялось"
    if city and city in text and club.split()[0] in text:
        return "подтверждено"
    if city and city in text:
        return "город есть, название клуба — проверить"
    return "проверить по ID в игре"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zone", action="append", help="зона (можно несколько раз)")
    ap.add_argument("--lang-db", default=None, help="lang_db.dat для сверки имён")
    ap.add_argument("--boost", action="store_true", help="добавить BOOST_TEAM к поднятым клубам")
    ap.add_argument("--money", type=int, default=150_000)
    ap.add_argument("--reputation", type=int, default=1600)
    args = ap.parse_args()

    second = read_csv(DATA / "second_division_2007.csv")
    first = read_csv(DATA / "first_division_2007.csv")
    zones = args.zone or list(dict.fromkeys(r["zone"] for r in second))

    text = ru_strings(Path(args.lang_db)) if args.lang_db else None
    if text is not None:
        print(f"строк в русской таблице: {len(text):,} символов")

    EDT.mkdir(exist_ok=True)
    report = ["# Перенос Второго дивизиона в играбельный уровень", ""]
    if text is None:
        report += ["> Сверка имён не выполнялась (`--lang-db` не указан).", ""]

    total_lines = 0
    for zone in zones:
        if zone not in EDT_RUS:
            raise SystemExit(f"неизвестная зона: {zone}")
        zclubs = [r for r in second if r["zone"] == zone]
        if len(zclubs) > len(first):
            raise SystemExit(f"в зоне {zone} {len(zclubs)} клубов, а мест в Первом дивизионе {len(first)}")

        pairs = pair_up(zclubs, first)
        lines = [
            f'"SWAP_TEAMS" "{a["full"]}" "{b["full"]}"' for a, b in pairs
        ]
        if args.boost:
            lines.append("")
            for a, _ in pairs:
                lines.append(f'"BOOST_TEAM" "{a["full"]}" {args.money} {args.reputation} -1')

        out = EDT / f"second_division_{EDT_RUS[zone]}.edt"
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        total_lines += len(pairs)

        report += [f"## Зона «{zone}» → `edt/{out.name}`", "",
                   f"Клубов поднято: **{len(pairs)}** из {len(zclubs)}.", "",
                   "| # | Клуб (Второй дивизион) | Меняется с (Первый дивизион) | Сверка имени |",
                   "|---|---|---|---|"]
        for a, b in pairs:
            conf = confidence(a["club"], a["city"], text)
            report.append(f"| {a['position']} | {a['club']} ({a['city']}) | {b['club']} ({b['city']}) | {conf} |")
        left = first[len(pairs):]
        if left:
            names = ", ".join(f"{r['club']} ({r['city']})" for r in left)
            report.append("")
            report.append(f"Остаются в Первом дивизионе без изменений: {names}.")
        report.append("")

    report += [
        "## Как применить", "",
        "1. Скопировать нужный `.edt` в `<папка игры>/data/db/`.",
        "2. Запустить игру и начать **новую** игру (старые сохранения не меняются).",
        "3. Клубы из файла теперь играют в Первом дивизионе — за них можно взять команду.",
        "",
        "Если имя в `.edt` не совпало с игровым, строка просто не сработает, и это "
        "видно сразу: клуб останется на прежнем месте. Тогда включите в игре "
        "*Preferences → Show Unique IDs*, откройте клуб и замените название на числовой ID.",
        "",
    ]
    (DATA / "swap_report.md").write_text("\n".join(report), encoding="utf-8")

    print(f"файлов .edt: {len(zones)}, строк SWAP_TEAMS: {total_lines}")
    print(f"отчёт: {DATA / 'swap_report.md'}")


if __name__ == "__main__":
    main()
