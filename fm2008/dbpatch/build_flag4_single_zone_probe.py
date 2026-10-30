#!/usr/bin/env python3
"""Build an isolated FM08 probe registering only Russia's West group.

The parent ID probe exposed the Russian country and its groups but no clubs.
This follow-up registers one existing group ID (West, 130488) directly at tier
2 with flag 4, while replaying the original First Division registration. It is
a diagnostic probe, not a confirmed playable patch and not a calendar edit.
"""
from __future__ import annotations

import argparse
import hashlib
import struct
import zipfile
from pathlib import Path

import patch_exe

ZONE_ID = 130_488
ZONE_NAME = "Россия. Второй дивизион - Запад"
ZONE_TIER = 2
ZONE_FLAGS = 4

README = """FM2008 8.0.2 — тест одной зоны: регистрация Запада на ступени 2
==================================================================

Это ИЗОЛИРОВАННЫЙ диагностический тест, а не подтверждённый патч играбельности
и не правка календаря. Предыдущий тест регистрации родителя 8051008 / tier 2 /
flag 4 показал Россию и зоны, но не клубы. Этот вариант проверяет, изменится ли
состав участников, если напрямую зарегистрировать только одну существующую
зону — `Россия. Второй дивизион - Запад` (ID 130488) — на ступени 2 с флагом 4.

Что меняется:
* только `fm.exe` из FM2008 8.0.2 — добавляется один вызов штатной функции
  регистрации соревнования;
* исходная регистрация Первого дивизиона повторяется без изменения;
* база, правила fixture/calendar, пять зонных параметров и данные клубов не
  изменяются; клубы не переносятся.

НЕ объединяйте этот тест с другими пропатченными `fm.exe`: используйте исходный
`fm.exe` именно версии 8.0.2. Пакет безопасно проверяет только свой ожидаемый
вызов и свободную область кода; при несовпадении отказывается патчить.

ПРОВЕРКА В ИГРЕ
1. Скопируйте исходный `fm.exe` в резервную папку и закройте игру.
2. Распакуйте этот `fm.exe` в папку игры с заменой.
3. Создайте НОВУЮ игру на базе 8.0.2.
4. Проверьте: отображается ли Россия; появилась ли зона «Запад»; сколько в ней
   клубов; остались ли остальные зоны; создаются ли матчи.
5. После проверки верните исходный `fm.exe`. Старое сохранение не использовать.

Интерпретация:
* клубы появились только в «Западе» — прямую регистрацию группы нужно изучать
  дальше; это ещё не доказывает, что такой путь безопасен для всех зон;
* зона появилась без клубов — регистрация группы сама по себе не наполняет её;
* Россия пропала, игра зависла или выдала ошибку — сразу вернуть исходный файл.

SHA256SUMS.txt содержит SHA-256 пропатченного `fm.exe`.
"""


def build_stub() -> bytes:
    """Replay the original call, register West at tier 2 / flag 4, then return."""
    code = bytearray()
    va = patch_exe.STUB_VA

    def emit(chunk: bytes) -> None:
        nonlocal va
        code.extend(chunk)
        va += len(chunk)

    # The original call's three arguments remain on the stack at the hook site.
    emit(b"\x8B\xCE")
    emit(patch_exe.call_rel(va, patch_exe.REGISTER_VA))

    emit(bytes((0x6A, ZONE_FLAGS)))
    emit(bytes((0x6A, ZONE_TIER)))
    emit(b"\x68" + struct.pack("<I", ZONE_ID))
    emit(b"\x8B\xCE")
    emit(patch_exe.call_rel(va, patch_exe.REGISTER_VA))
    emit(patch_exe.jmp_rel(va, patch_exe.RETURN_VA))
    if len(code) > patch_exe.STUB_SPACE:
        raise ValueError(f"stub exceeds reserved area: {len(code)} bytes")
    return bytes(code)


def patch_bytes(source: bytes) -> bytes:
    blob = bytearray(source)
    if blob[patch_exe.HOOK_RAW:patch_exe.HOOK_RAW + 5] != patch_exe.ORIGINAL_HOOK:
        raise ValueError("unexpected hook; expected the supported FM2008 8.0.2 fm.exe")
    cave = patch_exe.STUB_RAW
    if blob[cave:cave + patch_exe.STUB_SPACE] != b"\x90" * patch_exe.STUB_SPACE:
        raise ValueError("reserved .cave is occupied; refusing a different executable")

    stub = build_stub()
    blob[cave:cave + len(stub)] = stub
    blob[patch_exe.HOOK_RAW:patch_exe.HOOK_RAW + 5] = patch_exe.jmp_rel(
        patch_exe.HOOK_VA, patch_exe.STUB_VA
    )
    patch_exe.update_checksum(blob)
    result = bytes(blob)
    verify_bytes(source, result)
    return result


def verify_bytes(source: bytes, patched: bytes) -> None:
    if len(source) != len(patched):
        raise ValueError("executable size changed")
    stub = build_stub()
    allowed = set(range(patch_exe.HOOK_RAW, patch_exe.HOOK_RAW + 5))
    allowed.update(range(patch_exe.STUB_RAW, patch_exe.STUB_RAW + len(stub)))
    changed = {i for i, (old, new) in enumerate(zip(source, patched)) if old != new}
    if changed - allowed:
        pe_off = struct.unpack_from("<I", source, 0x3C)[0]
        checksum = set(range(pe_off + 24 + 64, pe_off + 24 + 68))
        if changed - allowed - checksum:
            raise ValueError("unexpected executable changes outside hook, stub, checksum")

    expected_hook = patch_exe.jmp_rel(patch_exe.HOOK_VA, patch_exe.STUB_VA)
    if patched[patch_exe.HOOK_RAW:patch_exe.HOOK_RAW + 5] != expected_hook:
        raise ValueError("hook verification failed")
    if patched[patch_exe.STUB_RAW:patch_exe.STUB_RAW + len(stub)] != stub:
        raise ValueError("stub verification failed")

    original_call = b"\x8B\xCE" + patch_exe.call_rel(
        patch_exe.STUB_VA + 2, patch_exe.REGISTER_VA
    )
    if not stub.startswith(original_call):
        raise ValueError("original First Division registration replay failed")
    zone_call = (
        bytes((0x6A, ZONE_FLAGS, 0x6A, ZONE_TIER, 0x68))
        + struct.pack("<I", ZONE_ID)
    )
    if stub.count(zone_call) != 1:
        raise ValueError("single West group registration not found")
    if stub.count(b"\xE8") != 2:
        raise ValueError("expected exactly original + one test registration calls")


def build_archive(exe: Path, out_dir: Path) -> Path:
    source = exe.read_bytes()
    patched = patch_bytes(source)
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / "fm2008-second-division-west-single-zone-probe.zip"
    digest = hashlib.sha256(patched).hexdigest()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("fm.exe", patched)
        zf.writestr("ЧИТАЙ_МЕНЯ.txt", README)
        zf.writestr("SHA256SUMS.txt", f"{digest}  fm.exe\n")
    return archive


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", required=True, type=Path, help="original FM2008 8.0.2 fm.exe")
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
