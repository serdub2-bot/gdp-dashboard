#!/usr/bin/env python3
"""Build a controlled follow-up probe for Russian Second Division groups.

Keeps the parent registration that the user verified (8051008, tier 2,
flag 4), then changes only the five info-table upper-bound arguments from -1
to -2. The game's 0xd35180 helper resolves -2 to the stated team count, giving
fixed group sizes like the Spanish B and Norwegian second-division examples.
This is an experiment, not a confirmed playable patch.
"""
from __future__ import annotations

import argparse
import hashlib
import struct
import zipfile
from pathlib import Path

import build_flag4_parent_probe as parent_probe
import build_parent_group_release as prior_probe
import patch_exe

PARENT_ID = parent_probe.PARENT_ID
PARENT_TIER = parent_probe.PARENT_TIER
PARENT_FLAGS = parent_probe.PARENT_FLAGS
FLAG_SITES = prior_probe.FLAG_SITES
FLAG_FROM = prior_probe.FLAG_FROM
FLAG_TO = prior_probe.FLAG_TO

README = """FM2008 8.0.2 — диагностический тест фиксированного числа команд в зонах
==========================================================================

ПРЕДЫДУЩИЙ ТЕСТ (flag4-parent-probe) показал: Россия и пять зон видны, но
команд нет. Этот пакет сохраняет уже проверенную регистрацию родителя
8051008 / tier 2 / flag 4 и проверяет следующее отличие от Испании B и
Норвегии. Второй дивизион: диапазон количества команд в их дочерних группах
фиксирован (20..20 и 14..14), а у российских зон штатный верхний предел
задан как открытый (16..65535, 13..65535 и т. д.).

В игре функция сведений 0xd35180 преобразует параметр -2 в указанное рядом
число, то есть задаёт одинаковые нижнюю и верхнюю границы. Параметр -1
сохраняет верхнюю границу 65535. Пакет меняет пять аргументов -1 на -2,
не меняя сами числа команд (16, 16, 13, 10, 12).

Меняется только fm.exe. Файлы базы, ID соревнований и клубы не изменяются;
клубы не переносятся. Это эксперимент, а не подтверждённый патч.

УСТАНОВКА ДЛЯ ТЕСТА
1. Сохраните проверенный fm.exe с flag4-parent-probe и исходный файл отдельно.
2. Закройте игру; распакуйте fm.exe из этого архива в папку игры.
3. Начните новую карьеру на базе 8.0.2.
4. Проверьте наличие России, пяти зон и число клубов в каждой.
5. Для отката верните исходный fm.exe.

SHA256SUMS.txt содержит контрольную сумму fm.exe.
"""


def patch_bytes(source: bytes) -> bytes:
    blob = bytearray(source)
    if blob[patch_exe.HOOK_RAW:patch_exe.HOOK_RAW + 5] != patch_exe.ORIGINAL_HOOK:
        raise ValueError("unexpected hook; expected the supported FM2008 8.0.2 fm.exe")
    cave = patch_exe.STUB_RAW
    if blob[cave:cave + patch_exe.STUB_SPACE] != b"\x90" * patch_exe.STUB_SPACE:
        raise ValueError("reserved .cave is occupied; refusing a different executable")
    for comp_id, site in FLAG_SITES.items():
        if blob[site:site + 2] != FLAG_FROM:
            raise ValueError(f"zone {comp_id}: expected push -1 at file offset {site}")

    stub = parent_probe.build_stub()
    blob[cave:cave + len(stub)] = stub
    blob[patch_exe.HOOK_RAW:patch_exe.HOOK_RAW + 5] = patch_exe.jmp_rel(
        patch_exe.HOOK_VA, patch_exe.STUB_VA
    )
    for site in FLAG_SITES.values():
        blob[site:site + 2] = FLAG_TO
    patch_exe.update_checksum(blob)
    result = bytes(blob)
    verify_bytes(source, result)
    return result


def verify_bytes(source: bytes, patched: bytes) -> None:
    if len(source) != len(patched):
        raise ValueError("executable size changed")
    stub = parent_probe.build_stub()
    expected = set(range(patch_exe.HOOK_RAW, patch_exe.HOOK_RAW + 5))
    expected.update(range(patch_exe.STUB_RAW, patch_exe.STUB_RAW + len(stub)))
    expected.update(site + 1 for site in FLAG_SITES.values())
    changed = {i for i, (old, new) in enumerate(zip(source, patched)) if old != new}
    if changed - expected:
        pe_off = struct.unpack_from("<I", source, 0x3C)[0]
        checksum = set(range(pe_off + 24 + 64, pe_off + 24 + 68))
        if changed - expected - checksum:
            raise ValueError("unexpected bytes changed outside hook, stub, flags, checksum")
    if source[patch_exe.HOOK_RAW:patch_exe.HOOK_RAW + 5] != patch_exe.ORIGINAL_HOOK:
        raise ValueError("source hook does not match")
    if patched[patch_exe.HOOK_RAW:patch_exe.HOOK_RAW + 5] != patch_exe.jmp_rel(
        patch_exe.HOOK_VA, patch_exe.STUB_VA
    ):
        raise ValueError("hook verification failed")
    if patched[patch_exe.STUB_RAW:patch_exe.STUB_RAW + len(stub)] != stub:
        raise ValueError("registration stub verification failed")
    for comp_id, site in FLAG_SITES.items():
        if source[site:site + 2] != FLAG_FROM or patched[site:site + 2] != FLAG_TO:
            raise ValueError(f"zone {comp_id}: info parameter verification failed")


def build_archive(exe: Path, out_dir: Path) -> Path:
    source = exe.read_bytes()
    patched = patch_bytes(source)
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / "fm2008-second-division-flag4-fixed-groups-probe.zip"
    digest = hashlib.sha256(patched).hexdigest()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("fm.exe", patched)
        zf.writestr("ЧИТАЙ_МЕНЯ.txt", README)
        zf.writestr("SHA256SUMS.txt", f"{digest}  fm.exe\n")
    return archive


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", required=True, type=Path, help="original fm.exe")
    parser.add_argument("--out", type=Path, default=Path("ready"))
    args = parser.parse_args()
    if not args.exe.is_file():
        raise SystemExit(f"missing executable: {args.exe}")
    try:
        archive = build_archive(args.exe, args.out)
    except (ValueError, struct.error) as exc:
        raise SystemExit(str(exc)) from exc
    print(f"archive: {archive} ({archive.stat().st_size:,} bytes)")
    with zipfile.ZipFile(archive) as zf:
        print(f"SHA256 fm.exe: {hashlib.sha256(zf.read('fm.exe')).hexdigest()}")


if __name__ == "__main__":
    main()
