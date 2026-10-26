#!/usr/bin/env python3
"""Сверка состава Третьей лиги 2007 с тем, что уже есть в базе FM2008.

Берёт `lang_db.dat` из папки `db` установленной игры, находит в нём русскую
таблицу строк (чанки zlib, по одному на язык), вытаскивает все строки и
проверяет, какие города и названия клубов из `data/clubs_2007.csv` в базе
уже присутствуют, а какие придётся создавать в Data Editor.

Использование:
    python3 fm2008/tools/lang_scan.py "/путь/к/db/lang_db.dat"
    python3 fm2008/tools/lang_scan.py lang_db.dat --csv out.csv --md out.md

По умолчанию отчёты пишутся в fm2008/third-league-russia/data/.
"""
from __future__ import annotations

import argparse
import csv
import re
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "fm2008" / "third-league-russia" / "data"


def zlib_chunks(blob: bytes) -> list[bytes]:
    """Все успешно распакованные zlib-потоки, начинающиеся с 78 9c."""
    out: list[bytes] = []
    seen: set[bytes] = set()
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
        key = buf[:2048]
        if key in seen:
            continue
        seen.add(key)
        out.append(buf)
    return out


def find_russian(chunks: list[bytes]) -> tuple[int, str]:
    """Чанк с наибольшим числом кириллических слов — русская локализация."""
    best, best_text = 0, ""
    for idx, buf in enumerate(chunks):
        text = buf.decode("utf-16-le", errors="ignore")
        n = len(re.findall(r"[А-ЯЁа-яё]{3,}", text))
        if n > best:
            best, best_text = n, text
    return best, best_text


def load_clubs(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("lang_db", help="путь к lang_db.dat из папки db игры")
    ap.add_argument("--clubs", default=str(DATA / "clubs_2007.csv"))
    ap.add_argument("--csv", default=str(DATA / "fm2008_match.csv"))
    ap.add_argument("--md", default=str(DATA / "fm2008_match.md"))
    args = ap.parse_args()

    blob = Path(args.lang_db).read_bytes()
    chunks = zlib_chunks(blob)
    n_ru, text = find_russian(chunks)
    print(f"чанков zlib: {len(chunks)}; в русском {n_ru:,} кириллических слов")

    rows = load_clubs(Path(args.clubs))
    out_rows = []
    for r in rows:
        club_ok = r["club"] in text
        city_ok = r["city"] in text
        out_rows.append({
            "zone": r["zone"],
            "subzone": r["subzone"],
            "position": r["position"],
            "club": r["club"],
            "city": r["city"],
            "city_in_db": "да" if city_ok else "нет",
            "club_in_db": "да" if club_ok else "нет",
            "action": "переиспользовать" if (club_ok and city_ok)
                      else "создать (город есть)" if city_ok
                      else "создать (нужен и город)",
        })

    with Path(args.csv).open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)

    cities = sorted({r["city"] for r in rows})
    clubs = sorted({r["club"] for r in rows})
    miss_city = [c for c in cities if c not in text]
    reuse = [r for r in out_rows if r["action"] == "переиспользовать"]
    need_city = [r for r in out_rows if r["action"] == "создать (нужен и город)"]

    lines = [
        "# Сверка с базой FM2008 (8.0.2)",
        "",
        f"Источник строк: `lang_db.dat`, русская таблица ({n_ru:,} кириллических слов).",
        "",
        "## Итог",
        "",
        f"- Городов из списка: **{len(cities)}**, найдено в базе: **{len(cities) - len(miss_city)}**",
        f"- Названий клубов: **{len(clubs)}**, найдено в базе: **{len(clubs) - len([c for c in clubs if c not in text])}**",
        f"- Клубов, которые можно взять готовыми (есть и клуб, и город): **{len(reuse)}** из {len(rows)}",
        f"- Клубов, где придётся создавать и город: **{len(need_city)}**",
        "",
        "## Города, которых в базе нет",
        "",
    ]
    lines += [f"- {c}" for c in miss_city] or ["— все города есть"]
    lines += ["", "## Готовые к переиспользованию клубы", ""]
    lines += ["| Зона | Клуб | Город |", "|---|---|---|"]
    lines += [f"| {r['zone']} | {r['club']} | {r['city']} |" for r in reuse] or ["| — | — | — |"]
    lines += ["", "Детально по каждому клубу — в `fm2008_match.csv`.", ""]
    Path(args.md).write_text("\n".join(lines), encoding="utf-8")

    print(f"готово: {args.csv}")
    print(f"готово: {args.md}")


if __name__ == "__main__":
    main()
