#!/usr/bin/env python3
"""Собрать эксперимент, повторяющий видимую схему Испании: parent + группы.

В базе ничего не меняется. В fm.exe регистрируется общий ID 8051008 на ступени
2, а пяти зональным строкам info-таблицы меняется параметр -1 -> -2. Это
непроверенная игровая гипотеза: самостоятельная смена флагов ранее скрывала
Россию, а регистрация одного родительского ID не добавляла команды. Их
совместная проверка нужна именно из-за испанского шаблона (umbrella registration
+ group info rows).
"""
from __future__ import annotations

import argparse
import hashlib
import struct
import zipfile
from pathlib import Path

import patch_exe

PARENT_ID = 8_051_008
PARENT_TIER = 2
FLAG_SITES = {
    130488: 11_058_183,
    130489: 11_058_117,
    130490: 11_058_161,
    130491: 11_058_139,
    8_055_759: 11_058_205,
}
FLAG_FROM = b"\x6A\xFF"  # push -1
FLAG_TO = b"\x6A\xFE"    # push -2

README = """FM2008 8.0.2 — эксперимент: общий ID + пять зон
===================================================

Это НЕ готовое решение, а одна контролируемая игровая проверка.

Основание: в Испании fm.exe регистрирует общий ID 121091 на ступени 2, а
отдельные строки info-таблицы описывают группы 69–72. В этом варианте России
регистрируется общий ID 8051008 на ступени 2, а пять зональных строк
130488–130491 и 8055759 получают параметр -2. client_db.dat и server_db.dat
не входят в архив и не изменяются: уровни российских групп остаются 2.
Клубы не переносятся.

Важно: по отдельности прежние проверки уже показали, что регистрация 8051008
не добавляет команды, а смена параметров зон на -2 скрывала Россию. Этот архив
проверяет только их сочетание по аналогии с Испанией. В FM2008 в песочнице
запустить его нельзя; результат должен быть подтверждён новой карьерой.

УСТАНОВКА
1. Закройте игру и сохраните резервную копию исходного fm.exe.
2. Распакуйте fm.exe из архива в папку игры с заменой.
3. Не меняйте файлы базы данных для этого теста.
4. Создайте новую карьеру и проверьте, что Россия остаётся в списке,
   а у Второго дивизиона появились зоны и команды.
5. Если Россия пропала или команды не появились — верните исходный fm.exe.

В архиве есть SHA256SUMS.txt для проверки файла.
"""


def build_stub() -> bytes:
    """Вставить регистрацию родителя перед исходной регистрацией Первого."""
    code = bytearray()
    va = patch_exe.STUB_VA

    def emit(chunk: bytes) -> None:
        nonlocal va
        code.extend(chunk)
        va += len(chunk)

    # Сначала выполнить исходную регистрацию 130487/tier 1 с уже подготовленными
    # аргументами — сохраняем порядок ступеней относительно Premier (tier 0).
    emit(b"\x8B\xCE")                                  # mov ecx, esi (nation)
    emit(patch_exe.call_rel(va, patch_exe.REGISTER_VA))
    emit(b"\x6A\x00")                                  # push 0 (flags)
    emit(bytes((0x6A, PARENT_TIER)))                   # push tier 2
    emit(b"\x68" + struct.pack("<I", PARENT_ID))      # push parent ID
    emit(b"\x8B\xCE")                                  # mov ecx, esi
    emit(patch_exe.call_rel(va, patch_exe.REGISTER_VA))
    emit(patch_exe.jmp_rel(va, patch_exe.RETURN_VA))
    if len(code) > patch_exe.STUB_SPACE:
        raise RuntimeError(f"stub exceeds reserved area: {len(code)} bytes")
    return bytes(code)


def patch_bytes(source: bytes) -> bytes:
    """Применить только одну регистрацию и пять точечных правок info-флагов."""
    blob = bytearray(source)
    start = patch_exe.HOOK_RAW
    if blob[start:start + 5] != patch_exe.ORIGINAL_HOOK:
        raise ValueError("неожиданный hook; ожидается исходный FM2008 8.0.2 fm.exe")
    cave = patch_exe.STUB_RAW
    if blob[cave:cave + patch_exe.STUB_SPACE] != b"\x90" * patch_exe.STUB_SPACE:
        raise ValueError("резервный .cave не пуст — это не исходный fm.exe")

    for comp_id, site in FLAG_SITES.items():
        if blob[site:site + 2] != FLAG_FROM:
            raise ValueError(f"zone {comp_id}: ожидался push -1 по смещению {site}")

    stub = build_stub()
    blob[cave:cave + len(stub)] = stub
    blob[start:start + 5] = patch_exe.jmp_rel(patch_exe.HOOK_VA, patch_exe.STUB_VA)
    for site in FLAG_SITES.values():
        blob[site:site + 2] = FLAG_TO
    patch_exe.update_checksum(blob)
    verify_bytes(source, bytes(blob))
    return bytes(blob)


def verify_bytes(source: bytes, patched: bytes) -> None:
    if len(source) != len(patched):
        raise ValueError("размер fm.exe изменился")
    changed = {i for i, (old, new) in enumerate(zip(source, patched)) if old != new}
    expected = set(range(patch_exe.HOOK_RAW, patch_exe.HOOK_RAW + 5))
    expected.update(range(patch_exe.STUB_RAW, patch_exe.STUB_RAW + len(build_stub())))
    for site in FLAG_SITES.values():
        expected.add(site + 1)  # only the immediate byte changes: FF -> FE
    if changed != expected:
        extra, missing = changed - expected, expected - changed
        raise ValueError(f"unexpected byte diff; extra={sorted(extra)}, missing={sorted(missing)}")
    if patched[patch_exe.STUB_RAW:patch_exe.STUB_RAW + len(build_stub())] != build_stub():
        raise ValueError("stub verification failed")
    for site in FLAG_SITES.values():
        if patched[site:site + 2] != FLAG_TO:
            raise ValueError("info flag verification failed")


def build_archive(exe: Path, out_dir: Path) -> Path:
    source = exe.read_bytes()
    patched = patch_bytes(source)
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / "fm2008-second-division-parent-groups-test.zip"
    digest = hashlib.sha256(patched).hexdigest()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("fm.exe", patched)
        zf.writestr("ЧИТАЙ_МЕНЯ.txt", README)
        zf.writestr("SHA256SUMS.txt", f"{digest}  fm.exe\n")
    return archive


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", required=True, type=Path, help="исходный fm.exe")
    parser.add_argument("--out", type=Path, default=Path("ready"))
    args = parser.parse_args()
    if not args.exe.is_file():
        raise SystemExit(f"нет файла {args.exe}")
    try:
        archive = build_archive(args.exe, args.out)
    except (ValueError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from exc
    print(f"архив: {archive} ({archive.stat().st_size:,} байт)")
    print(f"SHA256 fm.exe: {hashlib.sha256(zipfile.ZipFile(archive).read('fm.exe')).hexdigest()}")


if __name__ == "__main__":
    main()
