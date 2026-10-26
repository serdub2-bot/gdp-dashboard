#!/usr/bin/env python3
"""Поиск соревнований в базе FM2008: от названия до байтов в `client_db.dat`.

Шаги, которые выполняет скрипт:

1. в русской таблице `lang_db.dat` находит названия соревнований и их числовые
   ID (перед каждой строкой лежит `u32 id`, `u32 длина`);
2. ищет эти ID в распакованных `client_db.dat` / `server_db.dat`;
3. печатает найденные смещения и «окно» байтов вокруг каждого вхождения;
4. умеет сравнивать два соревнования (например, играбельное «Россия. Первый
   дивизион» и неиграбельное «Россия. Второй дивизион - Волга») и подсвечивать
   различающиеся байты — это и есть кандидаты в тот самый флаг «активности».

Использование:
    python3 hunt.py --db "/путь/к/db" --list-competitions
    python3 hunt.py --db ... --competition "Россия. Второй дивизион - Волга"
    python3 hunt.py --db ... --diff "Россия. Первый дивизион" "Россия. Второй дивизион - Волга"
"""
from __future__ import annotations

import argparse
import struct
from pathlib import Path

from si_db import Container, DbError, pick_russian, utf16_offsets, zlib_streams

TABLES = ("client_db.dat", "server_db.dat")


# ------------------------------------------------------------------ lang_db
def lang_blob(db: Path) -> bytes:
    path = db / "lang_db.dat"
    if not path.exists():
        raise SystemExit(f"нет файла {path}")
    blob = path.read_bytes()
    _, data = pick_russian(zlib_streams(blob))
    return data


def find_name(text_blob: bytes, name: str) -> dict | None:
    """Строка соревнования + её ID. Перед текстом: u32 id, u32 длина."""
    for off in utf16_offsets(text_blob, name):
        if off < 8:
            continue
        eid, tlen = struct.unpack_from("<II", text_blob, off - 8)
        if tlen * 2 == len(name.encode("utf-16-le")):
            return {"name": name, "offset": off, "id": eid}
        # строка может быть частью более длинного названия — тогда длина не совпадёт
        if 0 < tlen < 400:
            full = text_blob[off - 8 + 8: off - 8 + 8 + tlen * 2].decode("utf-16-le", "replace")
            return {"name": name, "offset": off, "id": eid, "full_name": full}
    return None


def list_competitions(text_blob: bytes, only: str = "Россия") -> list[dict]:
    """Все названия вида «Страна. Соревнование» с их ID."""
    found: list[dict] = []
    marker = only.encode("utf-16-le")
    pos = 0
    while True:
        idx = text_blob.find(marker, pos)
        if idx < 0:
            return found
        pos = idx + 2
        if idx < 8:
            continue
        eid, tlen = struct.unpack_from("<II", text_blob, idx - 8)
        if not (2 <= tlen <= 120):
            continue
        raw = text_blob[idx: idx + tlen * 2]
        try:
            name = raw.decode("utf-16-le")
        except UnicodeDecodeError:
            continue
        # отбрасываем куски, приклеенные к концу другой строки
        if not name.startswith(only) or any(ord(c) < 32 for c in name):
            continue
        found.append({"id": eid, "name": name, "offset": idx})


# ------------------------------------------------------------------ база
def occurrences(db: Path, target_id: int) -> dict[str, list[int]]:
    """Все смещения u32 `target_id` в распакованных таблицах."""
    raw = struct.pack("<I", target_id)
    out: dict[str, list[int]] = {}
    for name in TABLES:
        path = db / name
        if not path.exists():
            continue
        cont = Container.load(path)
        data = cont.decompressed()
        hits: list[int] = []
        pos = data.find(raw)
        while pos >= 0:
            hits.append(pos)
            pos = data.find(raw, pos + 1)
        out[name] = hits
    return out


def window(data: bytes, off: int, before: int = 24, after: int = 72) -> str:
    lo, hi = max(0, off - before), min(len(data), off + after)
    chunk = data[lo:hi]
    hexed = chunk.hex(" ")
    # подчёркиваем байты самого ID
    mark_at = (off - lo) * 3
    return f"{hexed[:mark_at]}[{hexed[mark_at:mark_at + 11]}]{hexed[mark_at + 11:]}"


def diff_windows(db: Path, a: dict, b: dict, span: int = 64) -> None:
    """Сравнить окна вокруг первых вхождений ID двух соревнований."""
    for name in TABLES:
        path = db / name
        if not path.exists():
            continue
        data = Container.load(path).decompressed()
        oa = data.find(struct.pack("<I", a["id"]))
        ob = data.find(struct.pack("<I", b["id"]))
        if oa < 0 or ob < 0:
            continue
        wa = data[oa: oa + span]
        wb = data[ob: ob + span]
        print(f"\n== {name}")
        print(f"  {a['name']} (id {a['id']}) @ {oa}")
        print(f"    {wa.hex(' ')}")
        print(f"  {b['name']} (id {b['id']}) @ {ob}")
        print(f"    {wb.hex(' ')}")
        marks = [
            f"{i:>3}:{x:02x}!={y:02x}" for i, (x, y) in enumerate(zip(wa, wb)) if x != y
        ]
        print("  различия:", ", ".join(marks) if marks else "нет (окна идентичны)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="папка db игры")
    ap.add_argument("--list-competitions", action="store_true", help="список соревнований")
    ap.add_argument("--only", default="Россия", help="префикс названий для --list-competitions")
    ap.add_argument("--competition", help="название соревнования, например 'Россия. Второй дивизион - Волга'")
    ap.add_argument("--diff", nargs=2, metavar=("A", "B"), help="сравнить два соревнования")
    args = ap.parse_args()

    db = Path(args.db)
    text_blob = lang_blob(db)
    print(f"русская таблица строк: {len(text_blob):,} байт")

    if args.list_competitions:
        items = list_competitions(text_blob, args.only)
        print(f"\nнайдено {len(items)} названий с префиксом «{args.only}»:")
        for it in items:
            print(f"  id={it['id']:<8} {it['name']}")

    if args.competition:
        info = find_name(text_blob, args.competition)
        if not info:
            raise SystemExit("название не найдено в русской таблице")
        print(f"\n{info['name']}: id={info['id']}, смещение в lang_db={info['offset']}")
        occ = occurrences(db, info["id"])
        for table, hits in occ.items():
            print(f"  {table}: {len(hits)} вхождений {hits[:10]}")
            cont = Container.load(db / table)
            data = cont.decompressed()
            for h in hits[:3]:
                print(f"    @{h}: {window(data, h)}")

    if args.diff:
        a, b = (find_name(text_blob, n) for n in args.diff)
        if not a or not b:
            raise SystemExit("одно из названий не найдено")
        diff_windows(db, a, b)


if __name__ == "__main__":
    main()
