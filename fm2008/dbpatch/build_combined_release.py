#!/usr/bin/env python3
"""Собрать единый тестовый пакет: регистрации в fm.exe + уровни в DB.

Именно сочетание этих двух частей ещё не проверялось в игре: один только exe
показывал пустые зоны, а один только DB не мог показать эти зоны в меню.
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

README = """FM2008 8.0.2 — совместный патч Второго дивизиона России
========================================================

Зачем этот архив
---------------
В предыдущем варианте был изменён только fm.exe: зоны появились в списке,
но остались пустыми. Отдельная правка уровней базы раньше проверялась без
регистраций в fm.exe, поэтому тоже не могла заполнить отображаемые зоны.
Этот пакет совмещает обе правки. Клубы между дивизионами не переносятся.

Установка (Windows)
-------------------
1. Полностью закройте игру.
2. Сделайте резервные копии своего fm.exe, а также
   data\\db\\802\\client_db.dat и data\\db\\802\\server_db.dat.
3. Извлеките файлы из архива, сохраняя папки:
   - fm.exe — в папку игры, заменив файл;
   - data\\db\\802\\client_db.dat и server_db.dat — в папку базы 8.0.2,
     заменив файлы.
4. Удалите кэш: Документы\\Sports Interactive\\Football Manager 2008\\cache
5. Начните новую игру и проверьте сначала список клубов в зонах.

Важно
-----
Это экспериментальный совместный вариант. Изменения байтов проверены скриптом,
но саму игру здесь запустить нельзя. Если игра не стартует или база не читается,
верните все три резервные копии. Старые сохранения не затрагиваются — проверять
нужно на новой игре.

Что меняется
------------
* fm.exe: добавляются пять регистраций зон (92-байтовый код и 5-байтовый переход).
* client_db.dat и server_db.dat: уровень пяти зарегистрированных соревнований
  меняется на 3; другие записи и клубные составы не меняются.
"""


def patch_db_file(path: Path, out_path: Path) -> tuple[bytes, int]:
    cont = Container.load(path)
    source = cont.decompressed()
    ops = activate.build_ops(source, "second3")
    if len(ops) != len(activate.SECOND):
        raise DbError(f"{path.name}: ожидалось {len(activate.SECOND)} изменений, найдено {len(ops)}")
    patched = activate.apply_ops(source, ops)
    activate.verify(source, patched, ops)
    packed = cont.pack(patched)
    check_path = out_path.with_suffix(out_path.suffix + ".check")
    check_path.parent.mkdir(parents=True, exist_ok=True)
    check_path.write_bytes(packed)
    check = Container.load(check_path).decompressed()
    check_path.unlink()
    if check != patched:
        raise DbError(f"{path.name}: контрольное чтение не совпало")
    return packed, len(ops)


def main() -> None:
    ap = argparse.ArgumentParser(description="Собрать совместный патч FM2008: exe + база")
    ap.add_argument("--exe", required=True, type=Path, help="оригинальный fm.exe")
    ap.add_argument("--db", required=True, type=Path, help="папка с client_db.dat и server_db.dat")
    ap.add_argument("--out", type=Path, default=Path("ready"), help="папка для zip")
    args = ap.parse_args()
    if not args.exe.is_file():
        raise SystemExit(f"нет файла {args.exe}")
    if not args.db.is_dir():
        raise SystemExit(f"нет папки {args.db}")

    args.out.mkdir(parents=True, exist_ok=True)
    archive = args.out / "fm2008-second-division-combined.zip"
    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        exe_out = tmp / "fm.exe"
        patch_exe.patch(args.exe, exe_out)
        patch_exe.verify(exe_out)

        payloads = {"fm.exe": exe_out.read_bytes()}
        change_counts = {}
        for filename in ("client_db.dat", "server_db.dat"):
            source = args.db / filename
            if not source.is_file():
                raise SystemExit(f"нет файла {source}")
            payloads[f"data/db/802/{filename}"], change_counts[filename] = patch_db_file(
                source, tmp / filename
            )

        sums = {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()}
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, data in payloads.items():
                zf.writestr(name, data)
            zf.writestr("ЧИТАЙ_МЕНЯ.txt", README)
            zf.writestr("SHA256SUMS.txt", "".join(f"{digest}  {name}\n" for name, digest in sums.items()))

    print(f"DB-изменения: client {change_counts['client_db.dat']}, server {change_counts['server_db.dat']}")
    print(f"архив: {archive} ({archive.stat().st_size / 1_000_000:.1f} МБ)")
    for name, digest in sums.items():
        print(f"  {digest}  {name}")


if __name__ == "__main__":
    main()
