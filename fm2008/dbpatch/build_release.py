#!/usr/bin/env python3
"""build_release.py — собрать готовый набор для установки.

Делает из исходной базы (папка `db` игры) архив с отдельной базой `rus2`,
которую видно в списке баз при старте новой игры. Так ничего не надо
перезаписывать: игра сама покажет, что новый набор прочитан.

    python3 build_release.py --db "/путь/data/db" --out ready
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import tempfile
import zipfile
from pathlib import Path

import activate
import patch_exe
from si_db import Container, DbError, compress_exact, pick_russian, zlib_streams

XML = """<!--
\tБаза для FM2008: Второй дивизион России.
\tИмя файла должно совпадать с именем папки, в которой он лежит.
-->
<properties version="1.0">
\t<string id="name" value="RUS2 - Second Division" translate="false" />
\t<string id="author" value="dbpatch" translate="false" />
\t<string id="description" value="Russian leagues 1-2-3-4" translate="false" />
\t<string id="version" value="8.0.2" translate="false" />
\t<string id="required_version" value="8.0.2" translate="false" />
</properties>
"""

README = """RUS2 — Второй дивизион России для FM2008
==========================================

ЧТО ЭТО
Отдельная копия базы. Она не заменяет вашу: игра сама предложит её при
старте новой игры. Ничего перезаписывать не нужно.

КАК ПОСТАВИТЬ (Windows)
1. Распакуйте архив в папку данных игры, рядом с папкой 802:

   ...\\Football Manager 2008\\data\\db\\

   Должно получиться так:

   data\\db\\802\\client_db.dat     <- ваша старая база, не трогаем
   data\\db\\rus2\\rus2.xml         <- новый набор
   data\\db\\rus2\\client_db.dat
   data\\db\\rus2\\server_db.dat
   data\\db\\rus2\\lang_db.dat

2. Удалите кэш: Документы\\Sports Interactive\\Football Manager 2008\\cache
3. Запустите игру -> Новая игра.
4. В списке баз (там, где версия 8.0.2) выберите "RUS2 - Second Division".
5. Дальше выбирайте лиги как обычно.

ЕСЛИ ПУНКТА "RUS2 - Second Division" В СПИСКЕ НЕТ
Значит игра смотрит в другую папку. Проверьте её скриптом find-db.bat:
он найдёт на диске все client_db.dat и покажет, где они лежат.

ЧТО ИЗМЕНЕНО
* client_db.dat, server_db.dat — 34 байта: шесть зон Второго дивизиона
  России получили уровень 3, одиннадцать зон Третьего — уровень 4.
* lang_db.dat — 155 байт: слово "Россия" заменено на "РОССИЯ" (31 место).
  Это метка: если в игре написано "РОССИЯ. Премьер-лига", значит файлы
  читаются, и вопрос уже только в самом признаке играбельности.
  Размер всех потоков сохранён байт в байт, ничего не сдвинуто.

ОТКАТ
Просто удалите папку data\\db\\rus2 и кэш.
"""


def patch_lang(db: Path) -> bytes:
    """lang_db.dat с заменой «Россия» -> «РОССИЯ» без сдвига потоков."""
    path = db / "lang_db.dat"
    blob = path.read_bytes()
    off, data = pick_russian(zlib_streams(blob))
    import zlib

    obj = zlib.decompressobj()
    obj.decompress(blob[off:])
    used = len(blob) - off - len(obj.unused_data)

    work = data.replace("Россия".encode("utf-16-le"), "РОССИЯ".encode("utf-16-le"))
    if work == data:
        raise DbError("в базе не нашлось «Россия» — другой файл?")
    stream = compress_exact(work, used)
    out = blob[:off] + stream + blob[off + used:]
    if len(out) != len(blob):
        raise DbError("размер lang_db изменился — так нельзя")
    return out


def patch_competitions(db: Path, variant: str) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for name in activate.TARGETS:
        cont = Container.load(db / name)
        src = cont.decompressed()
        ops = activate.build_ops(src, variant)
        if not ops:
            raise DbError(f"{name}: править нечего (уже пропатчено?)")
        patched = activate.apply_ops(src, ops)
        activate.verify(src, patched, ops)
        out[name] = cont.pack(patched)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", help="папка data/db игры (для сборки базы)")
    ap.add_argument("--exe", help="fm.exe (для сборки пропатченного exe)")
    ap.add_argument("--out", default="ready")
    ap.add_argument("--variant", default="pyramid")
    args = ap.parse_args()
    if args.exe:
        build_exe(Path(args.exe), Path(args.out))
        return
    if not args.db:
        raise SystemExit("нужен --db или --exe")

    db = Path(args.db)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    files = patch_competitions(db, args.variant)
    files["lang_db.dat"] = patch_lang(db)

    sums = {name: hashlib.sha256(blob).hexdigest() for name, blob in files.items()}
    print("готово, размеры:")
    for name, blob in files.items():
        print(f"  {name:<16} {len(blob):>10,} байт  sha256 {sums[name][:16]}")

    archive = out_dir / "fm2008-rus2-database.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, blob in files.items():
            zf.writestr(f"rus2/{name}", blob)
        zf.writestr("rus2/rus2.xml", XML)
        zf.writestr("ЧИТАЙ_МЕНЯ.txt", README)
        zf.writestr("SHA256SUMS.txt", "".join(f"{h}  {n}\n" for n, h in sums.items()))
    print(f"\nархив: {archive} ({archive.stat().st_size / 1e6:.1f} МБ)")


EXE_README = """FM2008: Второй дивизион России — включён в самой игре
=========================================================

ПОЧЕМУ ПАТЧИЛСЯ fm.exe, А НЕ БАЗА
Список играбельных дивизионов в FM2008 зашит в fm.exe, а не в базе данных.
Для каждой страны там есть список дивизионов по порядку, и у России в нём
всего два: Премьер-лига и Первый дивизион (у Англии — шесть, у Испании — три).
Поэтому Второй дивизион не появлялся в игре, что бы мы ни меняли в файлах базы.

ЧТО ИЗМЕНЕНО (исправленная версия)
В fm.exe добавлены пять регистраций зон Второго дивизиона:
  Запад, Центр, Юг, Восток, Урал/Волга.

Признаки зон во второй таблице не меняются. В предыдущем варианте я
ошибочно заменил их с -1 на -2: после этого Россия пропала из выбора стран.
В этой исправленной версии оставлены только добавленные регистрации — тот
вариант, с которым Россия была видна и лиги выбирались.

Изменено 97 байт из 22 249 472: 92-байтовый код-перехватчик и 5-байтовый
переход к нему. Ничего не сдвинуто, длина файла та же.

УСТАНОВКА
  1. Закройте игру.
  2. Найдите fm.exe (обычно в папке игры, рядом с fmdata) и скопируйте
     его в сторонку — это ваш откат.
  3. Замените fm.exe файлом fm.exe из этого архива.
  4. Удалите кэш: Документы\Sports Interactive\Football Manager 2008\cache
  5. Запустите игру -> Новая игра -> выбор лиг -> Россия.
     В списке лиг России должны появиться зоны Второго дивизиона.

Файлы базы (client_db.dat и остальные) можно оставить оригинальными:
патч от них не зависит. Если вы их уже заменяли на мои — желательно
вернуть свои, чтобы проверять по одному изменению за раз.

ОТКАТ
Вернуть старый fm.exe. Всё.

ЕСЛИ В СПИСКЕ ЛИГ НИЧЕГО НЕ ПОЯВИЛОСЬ
Значит для запуска дивизиона игре нужно ещё и описание правил
(число туров, обмен местами с дивизионом выше). Напишите, что показал
список лиг, и я продолжу с этого места.
"""


def build_exe(exe: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    patched = out_dir / "fm.exe"
    patch_exe.patch(exe, patched)
    digest = hashlib.sha256(patched.read_bytes()).hexdigest()
    archive = out_dir / "fm2008-exe-second-division.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(patched, arcname="fm.exe")
        zf.writestr("ЧИТАЙ_МЕНЯ.txt", EXE_README)
        zf.writestr("SHA256SUMS.txt", f"{digest}  fm.exe\n")
    patched.unlink()
    print(f"архив: {archive} ({archive.stat().st_size / 1e6:.1f} МБ)")


if __name__ == "__main__":
    try:
        main()
    except DbError as exc:
        print(f"ошибка: {exc}", file=sys.stderr)
        raise SystemExit(1)
