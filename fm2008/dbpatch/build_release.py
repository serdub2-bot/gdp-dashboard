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
    ap.add_argument("--db", required=True)
    ap.add_argument("--out", default="ready")
    ap.add_argument("--variant", default="pyramid")
    args = ap.parse_args()

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


if __name__ == "__main__":
    try:
        main()
    except DbError as exc:
        print(f"ошибка: {exc}", file=sys.stderr)
        raise SystemExit(1)
