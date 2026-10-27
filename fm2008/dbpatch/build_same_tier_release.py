#!/usr/bin/env python3
"""Собрать эксперимент: пять зон на одной ступени + уровень 3 в DB.

Предыдущие попытки регистрировали зоны последовательно (2,3,4,5,6) и
отдельно меняли уровень базы. Этот пакет проверяет связку: все пять зон —
параллельные группы одного уровня, поэтому каждая получает tier=2; записи
соревнований получают уровень 3. Флаги -1/-2 не меняются.
"""
from __future__ import annotations

import argparse
import hashlib
import tempfile
import zipfile
from pathlib import Path

import activate
import patch_exe
from si_db import Container, DbError

README = """FM2008 8.0.2 — эксперимент: пять зон Второго дивизиона на одной ступени
==========================================================================

В прошлых вариантах зоны регистрировались как пять последовательных уровней
2–6 либо регистрировался общий ID 8051008. Ни один вариант не добавил клубы.
Здесь проверяется другая структура: пять зон — параллельные группы одной
ступени, поэтому все пять зарегистрированы на ступени 2. В двух файлах базы
уровень этих пяти зон поставлен 3 (ниже Первого дивизиона, уровень 2).

Это экспериментальная гипотеза. Игра в этой среде не запускается, результат
не подтверждён. Флаги соревнований -1/-2 не изменяются, клубы не переносятся.

УСТАНОВКА
1. Закройте игру и сохраните копии fm.exe, client_db.dat, server_db.dat.
2. Распакуйте архив с сохранением путей:
   fm.exe -> папка игры;
   data\\db\\802\\client_db.dat и server_db.dat -> папка базы 8.0.2.
3. Удалите кэш Football Manager 2008.
4. Начните новую карьеру и проверьте список и состав всех пяти зон.
5. Если игра не загрузит базу, верните три резервные копии.
"""


def patch_db(path: Path) -> tuple[bytes, int]:
    cont = Container.load(path)
    before = cont.decompressed()
    ops = activate.build_ops(before, "second3")
    if len(ops) != len(activate.SECOND):
        raise DbError(f"{path.name}: ожидалось 5 правок, найдено {len(ops)}")
    after = activate.apply_ops(before, ops)
    activate.verify(before, after, ops)
    packed = cont.pack(after)
    test_path = Path(tempfile.gettempdir()) / f"fm2008-check-{path.name}"
    test_path.write_bytes(packed)
    try:
        if Container.load(test_path).decompressed() != after:
            raise DbError(f"{path.name}: контрольное чтение не совпало")
    finally:
        test_path.unlink(missing_ok=True)
    return packed, len(ops)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", required=True, type=Path, help="исходный fm.exe")
    ap.add_argument("--db", required=True, type=Path, help="папка исходных DB-файлов 8.0.2")
    ap.add_argument("--out", type=Path, default=Path("ready"))
    args = ap.parse_args()
    if not args.exe.is_file() or not args.db.is_dir():
        raise SystemExit("проверьте --exe и --db")

    with tempfile.TemporaryDirectory() as td:
        exe_patched = Path(td) / "fm.exe"
        patch_exe.patch(args.exe, exe_patched)
        patch_exe.verify(exe_patched)
        payloads = {"fm.exe": exe_patched.read_bytes()}

    counts: dict[str, int] = {}
    for name in ("client_db.dat", "server_db.dat"):
        src = args.db / name
        if not src.is_file():
            raise SystemExit(f"нет файла {src}")
        payloads[f"data/db/802/{name}"], counts[name] = patch_db(src)

    sums = {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()}
    args.out.mkdir(parents=True, exist_ok=True)
    archive = args.out / "fm2008-second-division-same-tier.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in payloads.items():
            zf.writestr(name, data)
        zf.writestr("ЧИТАЙ_МЕНЯ.txt", README)
        zf.writestr("SHA256SUMS.txt", "".join(f"{digest}  {name}\n" for name, digest in sums.items()))

    print(f"DB-правок: client={counts['client_db.dat']}, server={counts['server_db.dat']}")
    print(f"архив: {archive} ({archive.stat().st_size / 1_000_000:.1f} МБ)")
    for name, digest in sums.items():
        print(f"  {digest}  {name}")


if __name__ == "__main__":
    main()
