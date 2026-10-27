#!/usr/bin/env python3
"""Собрать кандидат с родительской регистрацией и исходной базой 8.0.2."""
from __future__ import annotations

import argparse
import hashlib
import tempfile
import zipfile
from pathlib import Path

import patch_exe
from si_db import Container

README = """FM2008 8.0.2 — кандидат: родительская регистрация Второго дивизиона
=======================================================================

В прошлых тестах отдельная регистрация пяти зон и правка их уровня не добавили
клубы. Этот кандидат регистрирует один общий ID 8051008 на ступени 2. В штатной
tаблице игры остаются пять зон и их числа команд. Такой способ регистрации
много-групповой ступени используется в английской конфигурации игры.

Это гипотеза по сравнению структур, а не подтверждённый результат. Саму игру
в этой среде запустить нельзя.

УСТАНОВКА
1. Закройте игру и сохраните копии fm.exe, client_db.dat и server_db.dat.
2. Распакуйте архив с сохранением путей:
   fm.exe -> папка игры;
   data\\db\\802\\client_db.dat и server_db.dat -> папка базы 8.0.2.
3. Удалите кэш Football Manager 2008.
4. Начните новую карьеру и проверьте Россию.

Базы в архиве — исходные файлы 8.0.2 без изменений. Если вы тестировали
эксперимент с изменением уровней, этот архив восстановит исходные client/server
базы. Клубы не переносятся. Если тест не поможет, верните три резервные копии.
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", required=True, type=Path, help="оригинальный fm.exe")
    ap.add_argument("--db", required=True, type=Path, help="папка с исходными DB-файлами")
    ap.add_argument("--out", type=Path, default=Path("ready"))
    args = ap.parse_args()
    if not args.exe.is_file() or not args.db.is_dir():
        raise SystemExit("проверьте --exe и --db")

    payloads: dict[str, bytes] = {}
    with tempfile.TemporaryDirectory() as td:
        patched = Path(td) / "fm.exe"
        patch_exe.patch(args.exe, patched)
        patch_exe.verify(patched)
        payloads["fm.exe"] = patched.read_bytes()

    for name in ("client_db.dat", "server_db.dat"):
        path = args.db / name
        if not path.is_file():
            raise SystemExit(f"нет файла {path}")
        # Проверяем round-trip чтение, но архивируем оригинальные байты без изменений.
        Container.load(path).decompressed()
        payloads[f"data/db/802/{name}"] = path.read_bytes()

    sums = {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()}
    args.out.mkdir(parents=True, exist_ok=True)
    archive = args.out / "fm2008-second-division-parent.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in payloads.items():
            zf.writestr(name, data)
        zf.writestr("ЧИТАЙ_МЕНЯ.txt", README)
        zf.writestr("SHA256SUMS.txt", "".join(f"{digest}  {name}\n" for name, digest in sums.items()))
    print(f"архив: {archive} ({archive.stat().st_size / 1_000_000:.1f} МБ)")
    for name, digest in sums.items():
        print(f"  {digest}  {name}")


if __name__ == "__main__":
    main()
