#!/usr/bin/env python3
"""Build a controlled FM08 probe for a grouped second-division registration.

Unlike earlier failed tests, this registers only the existing Russian umbrella
ID at tier 2 with registration flag 4, matching the call shape used by Spain B
and Norway's second division. It leaves every database file and all club data
untouched. This is an experiment, not a confirmed playable patch.
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
PARENT_FLAGS = 4

README = """FM2008 8.0.2 — диагностический тест grouped-league registration
==================================================================

Это НЕ подтверждённый патч играбельности. Пакет проверяет одну конкретную
гипотезу по шаблону из fm.exe: зарегистрировать существующий ID
8051008 «Россия. Второй дивизион» на ступени 2 с флагом 4 — так же, как
зарегистрированы Испания. Второй дивизион B и Норвегия. Второй дивизион.

Меняется только fm.exe. client_db.dat и server_db.dat не включены и не
изменяются. Клубы не переносятся; ID пяти зон и их штатные параметры сведений
не меняются. Это намеренно изолирует влияние флага регистрации от предыдущего
провалившегося теста, где использовался флаг 0 и одновременно менялись
параметры зон.

УСТАНОВКА ДЛЯ ТЕСТА
1. Сохраните исходный fm.exe отдельно и закройте игру.
2. Распакуйте fm.exe из архива в папку игры с заменой файла.
3. Начните новую карьеру на базе 8.0.2; старое сохранение не использовать.
4. Проверьте: (а) отображается ли Россия; (б) появились ли пять зон Второго
   дивизиона; (в) сколько клубов находится в каждой зоне.
5. Если Россия исчезла или игра выдаёт ошибку, верните исходный fm.exe.

Интерпретация: появление названий без команд означает, что один флаг не
исправил регистрацию участников. Появление команд подтвердит только этот
экспериментальный путь; перед выдачей финального патча результат нужно
повторить и проверить составы.

SHA256SUMS.txt позволяет проверить fm.exe в архиве.
"""


def build_stub() -> bytes:
    """Replay the original First registration, then add parent at flags=4."""
    code = bytearray()
    va = patch_exe.STUB_VA

    def emit(chunk: bytes) -> None:
        nonlocal va
        code.extend(chunk)
        va += len(chunk)

    # The hook replaces the original call; its three arguments are already
    # waiting on the stack, so consume them before setting up the new call.
    emit(b"\x8B\xCE")
    emit(patch_exe.call_rel(va, patch_exe.REGISTER_VA))

    emit(bytes((0x6A, PARENT_FLAGS)))
    emit(bytes((0x6A, PARENT_TIER)))
    emit(b"\x68" + struct.pack("<I", PARENT_ID))
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
    expected = set(range(patch_exe.HOOK_RAW, patch_exe.HOOK_RAW + 5))
    expected.update(range(patch_exe.STUB_RAW, patch_exe.STUB_RAW + len(stub)))
    changed = {i for i, (a, b) in enumerate(zip(source, patched)) if a != b}
    # update_checksum only touches the PE checksum when the source checksum was
    # valid; account for that optional 4-byte field without permitting other diffs.
    if changed - expected:
        pe_off = struct.unpack_from("<I", source, 0x3C)[0]
        checksum_off = pe_off + 24 + 64
        checksum_bytes = set(range(checksum_off, checksum_off + 4))
        if changed - expected - checksum_bytes:
            raise ValueError("unexpected executable changes outside hook, stub, checksum")
    if source[patch_exe.HOOK_RAW:patch_exe.HOOK_RAW + 5] != patch_exe.ORIGINAL_HOOK:
        raise ValueError("source hook does not match")
    expected_hook = patch_exe.jmp_rel(patch_exe.HOOK_VA, patch_exe.STUB_VA)
    if patched[patch_exe.HOOK_RAW:patch_exe.HOOK_RAW + 5] != expected_hook:
        raise ValueError("hook verification failed")
    if patched[patch_exe.STUB_RAW:patch_exe.STUB_RAW + len(stub)] != stub:
        raise ValueError("stub verification failed")
    if len(stub) < 3 or stub[:7] != b"\x8B\xCE" + patch_exe.call_rel(
        patch_exe.STUB_VA + 2, patch_exe.REGISTER_VA
    ):
        raise ValueError("original registration replay failed")
    parent_setup = (
        bytes((0x6A, PARENT_FLAGS, 0x6A, PARENT_TIER, 0x68))
        + struct.pack("<I", PARENT_ID)
    )
    if parent_setup not in stub:
        raise ValueError("parent ID/tier/flag setup not found")


def build_archive(exe: Path, out_dir: Path) -> Path:
    source = exe.read_bytes()
    patched = patch_bytes(source)
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / "fm2008-second-division-flag4-parent-probe.zip"
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
