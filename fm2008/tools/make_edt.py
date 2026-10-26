#!/usr/bin/env python3
"""Генератор .edt-файла для FM2008: поднять клубы Третьей лиги в дивизион выше.

Игра читает `data/db/*.edt` при старте новой игры. Команды, которые нужны здесь:

    "SWAP_TEAMS" "Клуб А" "Клуб Б"        — меняет клубы дивизионами
    "BOOST_TEAM" "Клуб" 200000 1800 -1    — баланс, репутация (100..10000), вместимость

Конфиг — JSON:
    {
      "swaps":  [["Истра", "Торпедо"], ...],
      "boosts": [["Истра", 200000, 1800, -1], ...]
    }

Важно: имена должны совпадать с тем, как клуб называется в игре, — включая
локализацию и все символы. Если не совпадает, надёжнее подставить Unique ID
(в игре: Preferences → «Show Unique IDs», затем открыть клуб).

Использование:
    python3 fm2008/tools/make_edt.py fm2008/data/plan.json -o out.edt
    python3 fm2008/tools/make_edt.py --example      # напечатать образец
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

EXAMPLE_JSON = {
    "swaps": [
        ["Истра", "Торпедо"],
        ["Химик", "Анжи"],
    ],
    "boosts": [
        ["Истра", 200000, 1800, -1],
        ["Химик", 150000, 1700, -1],
    ],
}


def render(cfg: dict) -> str:
    # никаких комментариев: парсер FM ожидает в каждой строке команду
    lines: list[str] = []
    for a, b in cfg.get("swaps", []):
        lines.append(f'"SWAP_TEAMS" "{a}" "{b}"')
    if cfg.get("swaps") and cfg.get("boosts"):
        lines.append("")
    for row in cfg.get("boosts", []):
        club, money, rep, stadium = row[0], row[1], row[2], row[3]
        if not (100 <= int(rep) <= 10000):
            raise SystemExit(f"репутация {rep} вне диапазона 100..10000 ({club})")
        lines.append(f'"BOOST_TEAM" "{club}" {money} {rep} {stadium}')
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("config", nargs="?", help="JSON с планом правок")
    ap.add_argument("-o", "--out", default="third_league_2007.edt")
    ap.add_argument("--example", action="store_true", help="напечатать образец конфига")
    args = ap.parse_args()

    if args.example:
        print(json.dumps(EXAMPLE_JSON, ensure_ascii=False, indent=2))
        return
    if not args.config:
        raise SystemExit("нужен JSON-конфиг (или --example)")

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    text = render(cfg)
    Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    print(f"записано: {args.out}")


if __name__ == "__main__":
    main()
