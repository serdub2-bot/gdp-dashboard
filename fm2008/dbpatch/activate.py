#!/usr/bin/env python3
"""activate.py — патч «сделать Второй дивизион России играбельным».

Идея патча. В базе FM2008 у каждого соревнования есть запись фиксированного
размера (54 байта), где лежит, среди прочего, номер уровня. У России он такой:

    Премьер-лига        1
    Первый дивизион     2
    Второй дивизион     2   <-- тот же уровень, что и у Первого!
    Третий дивизион     3

То есть Второй дивизион объявлен «вторым уровнем» наравне с Первым, а не
отдельной ступенью ниже. Патч ставит зонам Второго дивизиона свой уровень (3),
а Третьему — 4, чтобы ступени не пересекались.

Патч меняет единицы байт, ничего не сдвигает, полностью обратим (скрипт кладёт
рядом `*.orig`) и после записи сам перечитывает файл и сверяет, что изменились
ровно те байты, которые задумано.

Варианты (`--variant`):
    second3  (по умолчанию) — только шесть зон Второго дивизиона: 2 -> 3
    pyramid                 — плюс Третий дивизион: 3 -> 4 (и «Москва», «ЦГ2»: 2 -> 4)
    firstclone              — зонам копируются поля Первого дивизиона (грубый вариант)

Использование:
    python3 activate.py --db "/путь/data/db" --report "Россия"
    python3 activate.py --db "/путь/data/db" --variant second3 --dry-run
    python3 activate.py --db "/путь/data/db" --variant second3 --out out
    python3 activate.py --db "/путь/data/db" --variant second3 --out out --zip
"""
from __future__ import annotations

import argparse
import shutil
import struct
import sys
import zipfile
from pathlib import Path

from si_db import Container, DbError

TARGETS = ("client_db.dat", "server_db.dat")

# id соревнований России (из русской таблицы строк lang_db.dat)
SECOND = {
    130488: "Второй дивизион - Запад",
    130489: "Второй дивизион - Центр",
    130490: "Второй дивизион - Юг",
    130491: "Второй дивизион - Восток",
    130492: "Второй дивизион - Волга",
    130493: "Второй дивизион - Урал",
}
THIRD = {
    8050900: "Третий дивизион - Центральная группа 1",
    8050901: "Третий дивизион - Золотое кольцо",
    8050902: "Третий дивизион - Северо-Запад",
    8050903: "Третий дивизион - Юг",
    8050904: "Третий дивизион - Волга",
    8050905: "Третий дивизион - Дальний Восток",
    8050906: "Третий дивизион - Сибирь",
    8050907: "Третий дивизион - Урал",
    8050908: "Третий дивизион - Черноземье",
    8050940: "Третий дивизион - Москва",
    145435: "Третий дивизион - Центральная группа 2",
}
FIRST = 130487  # «Россия. Первый дивизион» — образец играбельного соревнования

# Подпись записи соревнования: сразу после u32 id идут байты 00 00 00 ff 7f 8c.
SIGNATURE = b"\x00\x00\x00\xff\x7f\x8c"

# Смещения полей относительно позиции u32 id (запись начинается на 8 байт раньше).
OFF_LEVEL_U32 = 20   # u32, старший байт = уровень
OFF_LEVEL = 23       # сам байт уровня
OFF_P1 = 36          # u32 — ссылка на доп. данные
OFF_P2 = 40          # u32 — ссылка на доп. данные
RECORD_BEFORE = 8
RECORD_SIZE = 54


# --------------------------------------------------------------- разбор базы
def find_record(data: bytes, comp_id: int) -> int | None:
    """Смещение u32 `comp_id` внутри записи соревнования (по подписи)."""
    needle = struct.pack("<I", comp_id)
    pos = data.find(needle)
    while pos >= 0:
        if data[pos + 4: pos + 10] == SIGNATURE:
            return pos
        pos = data.find(needle, pos + 1)
    return None


def scan_competitions(data: bytes) -> list[tuple[int, int]]:
    """Все записи соревнований в файле: список (id, смещение u32 id)."""
    out: list[tuple[int, int]] = []
    pos = 0
    while True:
        sig = data.find(SIGNATURE, pos)
        if sig < 0:
            return out
        pos = sig + 1
        if sig < 4:
            continue
        out.append((struct.unpack_from("<I", data, sig - 4)[0], sig - 4))


def level_of(data: bytes, off: int) -> int:
    return data[off + OFF_LEVEL]


def describe(data: bytes, off: int) -> str:
    start = max(0, off - RECORD_BEFORE)
    return data[start: start + RECORD_SIZE].hex(" ")


# ------------------------------------------------------------------- патчи
def build_ops(data: bytes, variant: str) -> list[dict]:
    """Список правок [(offset, expect, new, подпись)] под выбранный вариант."""
    ops: list[dict] = []

    def add(comp_id: int, name: str, new_level: int | None = None,
            copy_from: int | None = None) -> None:
        off = find_record(data, comp_id)
        if off is None:
            raise DbError(f"соревнование {comp_id} ({name}) не найдено в файле")
        if copy_from is not None:
            src = find_record(data, copy_from)
            if src is None:
                raise DbError(f"образец {copy_from} не найден")
            for delta in (20, 21, 22, 23, 36, 37, 38, 39, 40, 41, 42, 43):
                cur, want = data[off + delta], data[src + delta]
                if cur != want:
                    ops.append({"offset": off + delta, "expect": cur, "new": want,
                                "label": f"{name}: байт +{delta} как у Первого дивизиона"})
            return
        assert new_level is not None
        cur = data[off + OFF_LEVEL]
        if cur == new_level:
            return
        ops.append({"offset": off + OFF_LEVEL, "expect": cur, "new": new_level,
                    "label": f"{name}: уровень {cur} -> {new_level}"})

    if variant in ("second3", "pyramid"):
        for cid, name in SECOND.items():
            add(cid, name, new_level=3)
        if variant == "pyramid":
            for cid, name in THIRD.items():
                add(cid, name, new_level=4)
    elif variant == "firstclone":
        for cid, name in SECOND.items():
            add(cid, name, copy_from=FIRST)
    else:
        raise DbError(f"неизвестный вариант: {variant}")
    return ops


def apply_ops(data: bytes, ops: list[dict]) -> bytes:
    buf = bytearray(data)
    for op in ops:
        off, exp, new = op["offset"], op["expect"], op["new"]
        if buf[off] != exp:
            raise DbError(
                f"{op['label']}: по смещению {off} ожидался байт 0x{exp:02x}, "
                f"а лежит 0x{buf[off]:02x} — файл другой версии, патч отменён"
            )
        buf[off] = new
    return bytes(buf)


def verify(before: bytes, after: bytes, ops: list[dict]) -> None:
    if len(before) != len(after):
        raise DbError("после патча изменился размер таблицы — так быть не должно")
    changed = {op["offset"]: op["new"] for op in ops}
    for i, (a, b) in enumerate(zip(before, after)):
        if a == b:
            continue
        if i not in changed:
            raise DbError(f"изменился незапланированный байт по смещению {i}")
        if b != changed[i]:
            raise DbError(f"по смещению {i} ожидалось 0x{changed[i]:02x}, получено 0x{b:02x}")
    for off, want in changed.items():
        if after[off] != want:
            raise DbError(f"правка по смещению {off} не применилась")


# ------------------------------------------------------------------- отчёт
def report(db: Path, prefix: str) -> None:
    for name in TARGETS:
        path = db / name
        if not path.exists():
            continue
        data = Container.load(path).decompressed()
        recs = scan_competitions(data)
        print(f"\n== {name}: записей соревнований {len(recs)}")
        from hunt import lang_blob, list_competitions  # локальный импорт: нужен lang_db
        names = {i["id"]: i["name"] for i in list_competitions(lang_blob(db), "")}
        shown = 0
        for cid, off in recs:
            title = names.get(cid)
            if not title or not title.startswith(prefix):
                continue
            shown += 1
            print(f"  id={cid:<9} уровень={level_of(data, off):<4} @{off:<9} {title[:52]}")
        print(f"  показано {shown}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Патч «Второй дивизион России»")
    ap.add_argument("--db", required=True, help="папка data/db игры")
    ap.add_argument("--variant", default="second3", choices=("second3", "pyramid", "firstclone"))
    ap.add_argument("--out", help="куда положить пропатченные файлы (по умолчанию рядом)")
    ap.add_argument("--dry-run", action="store_true", help="только показать правки")
    ap.add_argument("--zip", action="store_true", help="упаковать результат в zip")
    ap.add_argument("--report", metavar="ПРЕФИКС", help="показать уровни соревнований, напр. 'Россия'")
    args = ap.parse_args()

    db = Path(args.db)
    if not db.is_dir():
        raise SystemExit(f"нет папки {db}")

    if args.report:
        report(db, args.report)
        return

    out_dir = Path(args.out) if args.out else db
    total = 0
    written: list[Path] = []
    for name in TARGETS:
        src = db / name
        if not src.exists():
            print(f"пропуск: нет файла {src}")
            continue
        cont = Container.load(src)
        data = cont.decompressed()
        ops = build_ops(data, args.variant)
        print(f"\n== {name}: правок {len(ops)}")
        for op in ops:
            print(f"   {op['label']}  @{op['offset']}  "
                  f"0x{op['expect']:02x} -> 0x{op['new']:02x}")
        total += len(ops)
        if not ops:
            print("   (уже пропатчено — менять нечего)")
            continue
        if args.dry_run:
            continue

        patched = apply_ops(data, ops)
        verify(data, patched, ops)
        out_dir.mkdir(parents=True, exist_ok=True)
        dst = out_dir / name
        if out_dir.resolve() == db.resolve():
            backup = src.with_suffix(src.suffix + ".orig")
            if not backup.exists():
                shutil.copy2(src, backup)
                print(f"   резервная копия: {backup.name}")
        cont.save(dst, patched)
        # контрольное чтение: файл должен открываться и содержать новые байты
        check = Container.load(dst).decompressed()
        if check[ops[0]["offset"]] != ops[0]["new"]:
            raise DbError(f"{dst}: после записи байт не изменился")
        print(f"   записано: {dst}")
        written.append(dst)

    if args.dry_run:
        print(f"\nвсего правок: {total}. Это был --dry-run, файлы не тронуты.")
        return
    if not written:
        print("\nнечего записывать")
        return

    if args.zip:
        archive = out_dir / f"fm2008-second-division-{args.variant}.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in written:
                zf.write(f, arcname=f"db/{f.name}")
        print(f"\nархив: {archive} ({archive.stat().st_size / 1e6:.1f} МБ)")

    print(f"\nвсего правок: {total}")
    print("Как проверить: заменить файлы в папке игры data\\db, запустить игру, "
          "начать новую игру и посмотреть список лиг России.")


if __name__ == "__main__":
    try:
        main()
    except DbError as exc:
        print(f"ошибка: {exc}", file=sys.stderr)
        raise SystemExit(1)
