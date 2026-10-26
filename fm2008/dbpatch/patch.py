#!/usr/bin/env python3
"""Патчер базы FM2008: проверяемые правки на уровне байтов.

Идея простая и безопасная:

1. патч — это JSON со списком операций и **ожидаемыми** байтами в каждой точке;
2. если `expect` не совпал, операция не применяется (значит, структура другая —
   лучше остановиться, чем записать мусор);
3. файл пишется в отдельную папку `out/`, оригинал не трогается;
4. после записи файл читается обратно и сверяется с ожидаемым результатом.

Операции:

    {"type": "assert",       "offset": 123, "expect": "789c"}
    {"type": "write_bytes",  "offset": 123, "expect": "4c6f6b6f", "data": "4c6f6b6c"}
    {"type": "write_u32",    "offset": 123, "expect": 5, "value": 6}
    {"type": "rename_string","expect": "Второй дивизион", "data": "Третья лига"}

`rename_string` работает по русской таблице строк: находит строку в UTF-16LE и
заменяет её на новую **той же длины в байтах** (короткая добивается пробелами).
Так не сдвигаются смещения и не ломается таблица.

Использование:

    python3 patch.py plan.json --db "/путь/к/db" --out out
    python3 patch.py plan.json --db ... --dry-run     # только проверки
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from si_db import (Container, DbError, pick_russian, utf16_offsets, zlib_streams)

TEXT_FILES = ("lang_db.dat",)


def _hex(value: str) -> bytes:
    return bytes.fromhex(value.replace(" ", ""))


def apply_byte_ops(data: bytearray, ops: list[dict], report: list[str]) -> bytearray:
    for i, op in enumerate(ops, 1):
        kind = op["type"]
        if kind == "assert":
            off = int(op["offset"])
            expect = _hex(op["expect"])
            got = bytes(data[off:off + len(expect)])
            if got != expect:
                raise DbError(f"операция {i} (assert): ожидалось {expect.hex()} по {off}, "
                              f"а там {got.hex()}")
            report.append(f"  [{i}] assert ок @ {off} ({expect.hex()})")

        elif kind == "write_bytes":
            off = int(op["offset"])
            expect = _hex(op["expect"])
            new = _hex(op["data"])
            if len(new) != len(expect):
                raise DbError(f"операция {i}: длина new ({len(new)}) != длина expect ({len(expect)})")
            got = bytes(data[off:off + len(expect)])
            if got != expect:
                raise DbError(f"операция {i}: в точке {off} не те байты: {got.hex()} != {expect.hex()}")
            data[off:off + len(new)] = new
            report.append(f"  [{i}] write_bytes ок @ {off}: {expect.hex()} -> {new.hex()}")

        elif kind == "write_u32":
            off = int(op["offset"])
            expect = int(op["expect"])
            value = int(op["value"])
            got = int.from_bytes(data[off:off + 4], "little")
            if got != expect:
                raise DbError(f"операция {i}: u32 @ {off} = {got}, ожидалось {expect}")
            data[off:off + 4] = value.to_bytes(4, "little")
            report.append(f"  [{i}] write_u32 ок @ {off}: {expect} -> {value}")

        else:
            raise DbError(f"операция {i}: неизвестный тип {kind!r}")
    return data


def apply_string_ops(path: Path, ops: list[dict], out_dir: Path, report: list[str],
                     dry_run: bool = False) -> Path | None:
    """Правки строк в lang_db.dat: тот же размер в байтах, без сдвига таблицы."""
    if not ops:
        return None

    blob = path.read_bytes()
    streams = zlib_streams(blob)
    off, data = pick_russian(streams)
    report.append(f"  русская таблица: смещение {off}, {len(data):,} байт")

    work = bytearray(data)
    for i, op in enumerate(ops, 1):
        old, new = op["expect"], op["data"]
        positions = utf16_offsets(bytes(work), old)
        if not positions:
            raise DbError(f"строка {i}: «{old}» не найдена в русской таблице")
        if len(positions) > int(op.get("max_hits", 1)):
            raise DbError(f"строка {i}: «{old}» встречается {len(positions)} раз — "
                          f"неоднозначно, уточните или поднимите max_hits")
        if len(new.encode("utf-16-le")) > len(old.encode("utf-16-le")):
            raise DbError(f"строка {i}: «{new}» длиннее «{old}» — смещения поедут")
        pad = new.ljust(len(old))
        raw = pad.encode("utf-16-le")
        for pos in positions:
            work[pos:pos + len(raw)] = raw
        report.append(f"  [{i}] строка «{old}» -> «{new}» (смещений: {len(positions)})")

    if dry_run:
        report.append("  dry-run: проверки пройдены, файл не записан")
        return None

    # пересобираем lang_db: заголовок + таблицы смещений как есть, меняем только поток
    head = blob[:off]
    tail_start = off + _stream_len(blob, off)
    tail = blob[tail_start:]
    new_stream = _recompress(work, blob[off:tail_start])

    out = out_dir / path.name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(head + new_stream + tail)

    back = pick_russian(zlib_streams(out.read_bytes()))[1]
    if back != bytes(work):
        raise DbError("после записи русская таблица не совпала — файл удалён")
    report.append(f"  проверка после записи: ок, {out}")
    return out


def _stream_len(blob: bytes, offset: int) -> int:
    """Длина zlib-потока, начинающегося в offset (по unused_data)."""
    import zlib as _z
    obj = _z.decompressobj()
    obj.decompress(blob[offset:])
    return len(blob) - offset - len(obj.unused_data)


def _recompress(data: bytes, original: bytes) -> bytes:
    """Пересжать так же, как было: сначала тем же уровнем, иначе максимумом."""
    import zlib as _z
    for level in (6, 9, 1):
        cand = _z.compress(bytes(data), level)
        if len(cand) <= len(original) + 64:
            return cand
    return _z.compress(bytes(data), 9)


def main() -> None:
    ap = argparse.ArgumentParser(description="Проверяемый патч базы FM2008")
    ap.add_argument("plan", help="JSON с планом правок")
    ap.add_argument("--db", required=True, help="папка db игры (источник)")
    ap.add_argument("--out", default="out", help="куда писать изменённые файлы")
    ap.add_argument("--dry-run", action="store_true", help="только проверки, без записи")
    args = ap.parse_args()

    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    db = Path(args.db)
    out_dir = Path(args.out)

    report: list[str] = []
    changed: list[Path] = []

    for target in plan.get("files", []):
        name = target["name"]
        src = db / name
        if not src.exists():
            raise SystemExit(f"нет файла {src}")
        report.append(f"\n== {name}")
        byte_ops = [op for op in target.get("ops", []) if op["type"] != "rename_string"]
        str_ops = [op for op in target.get("ops", []) if op["type"] == "rename_string"]

        if byte_ops:
            cont = Container.load(src)
            report.append(f"  {cont.describe()}")
            data = bytearray(cont.decompressed())
            data = apply_byte_ops(data, byte_ops, report)
            if args.dry_run:
                report.append("  dry-run: файл не записан")
            else:
                dst = out_dir / name
                if not dst.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst.with_suffix(".orig"))
                cont.save(dst, bytes(data))
                report.append(f"  записано: {dst}")
                changed.append(dst)

        if str_ops:
            if name != "lang_db.dat":
                raise SystemExit("rename_string поддерживается только для lang_db.dat")
            res = apply_string_ops(src, str_ops, out_dir, report, dry_run=args.dry_run)
            if res:
                changed.append(res)

    print("\n".join(report))
    print(f"\nготово. изменённых файлов: {len(changed)}")
    if changed:
        print("Положить изменённые файлы в <игра>/data/db/ (оригиналы сохранены рядом как *.orig).")


if __name__ == "__main__":
    main()
