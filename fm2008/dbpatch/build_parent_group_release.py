#!/usr/bin/env python3
"""Сборщик архивного экспериментального пакета, проверка которого провалилась.

Пакет регистрирует общий ID 8051008 на ступени 2 и меняет параметры пяти
зональных строк info-таблицы с -1 на -2; DB-файлы не меняются. Пользователь
проверил его: Россия пропала из списка выбора чемпионатов. Не использовать как
решение. Скрипт оставлен для воспроизводимости этой неудачной гипотезы.
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

README = """FM2008 8.0.2 — архивный неудачный тест: общий ID + пять зон
============================================================

Пакет регистрировал ID 8051008 на ступени 2 и менял параметры пяти зональных
строк 130488–130491 и 8055759 с -1 на -2. Файлы client_db.dat и server_db.dat
не менялись; клубы не переносились.

РЕЗУЛЬТАТ ПОЛЬЗОВАТЕЛЬСКОГО ТЕСТА: Россия пропала из списка выбора чемпионатов.
НЕ УСТАНАВЛИВАТЬ. Архив хранится только для воспроизведения провалившейся
гипотезы и сверки контрольной суммы.

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
    """Применить одну регистрацию и пять точечных параметров info-таблицы."""
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
