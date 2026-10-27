#!/usr/bin/env python3
"""patch_exe.py — включить Второй дивизион России в fm.exe.

Почему exe, а не база. В FM2008 список играбельных дивизионов зашит в саму игру:
для каждой страны есть функция, которая по очереди регистрирует дивизионы.

    push 0            ; третий аргумент (флаги)
    push <ступень>    ; 0, 1, 2, ...
    push <id соревнования>
    mov  ecx, <нация>
    call 0xd63c10     ; регистрация

У Англии таких вызовов шесть (Премьер, Первый, Второй, Третий, Конференция,
Конференция Север/Юг), у Испании три, у России — ровно два:

    130486 «Россия. Премьер-лига»          ступень 0
    130487 «Россия. Первый дивизион»       ступень 1
    ... и всё.

Поэтому Второй дивизион не появлялся, что бы мы ни писали в базе. При этом сам
exe отдельно описывает пять зон во второй таблице (call 0xd35180) вместе с
числом команд. Эксперимент с регистрацией каждой зоны по отдельности сделал
лиги видимыми, но команды не появились. Сравнение с Англией показало, что
много-групповая ступень регистрируется одним родительским соревнованием
(Conference / Blue Square North-South), а не дочерними турнирами отдельно.

Текущий кандидат регистрирует родительский ID 8051008 «Второй дивизион»
на ступени 2. Пять зон остаются дочерними записями штатной таблицы игры.
Это вывод из сравнения с Англией; результат нужно проверить в самой игре.
Переход к коду размещается в свободных NOP-байтах секции .cave, файл не
сдвигается и не меняет длину.

Использование:
    python3 patch_exe.py fm.exe --dry-run      # показать, что будет сделано
    python3 patch_exe.py fm.exe --out fm-patched.exe
    python3 patch_exe.py --revert fm-patched.exe --out fm-original.exe
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import struct
import sys
from pathlib import Path

# --- точки патча (файловые смещения; в этой сборке RVA == файловое смещение для .text)
HOOK_RAW = 11_057_861          # call 0xd63c10 — регистрация «Первый дивизион», ступень 1
HOOK_VA = 0xE8BAC5
RETURN_VA = 0xE8BACA           # mov edi, [esi+0x40] — куда вернуться
STUB_RAW = 0x1537824           # NOP-«полка» в .cave (2012 байт 0x90)
STUB_VA = 0x1C04824
STUB_SPACE = 2012
REGISTER_VA = 0xD63C10         # функция регистрации дивизиона: (id, ступень, флаги)

# что должно быть на месте до патча
ORIGINAL_HOOK = struct.pack("<BI", 0xE8, (REGISTER_VA - (HOOK_VA + 5)) & 0xFFFFFFFF)

# Родительское соревнование Второго дивизиона; его пять зон описаны отдельно
# в штатной таблице info (call 0xd35180).
SECOND_DIVISION = (8_051_008, 2, "Второй дивизион (общий)")


def call_rel(from_va: int, to_va: int) -> bytes:
    return b"\xE8" + struct.pack("<i", to_va - (from_va + 5))


def jmp_rel(from_va: int, to_va: int) -> bytes:
    return b"\xE9" + struct.pack("<i", to_va - (from_va + 5))


def build_stub() -> bytes:
    """Код: зарегистрировать общий Второй дивизион, выполнить исходный call и вернуться."""
    code = bytearray()
    va = STUB_VA

    def emit(chunk: bytes) -> None:
        nonlocal va
        code.extend(chunk)
        va += len(chunk)

    comp_id, tier, _ = SECOND_DIVISION
    emit(b"\x6A\x00")                           # push 0     (флаги)
    emit(bytes([0x6A, tier]))                   # push tier
    emit(b"\x68" + struct.pack("<I", comp_id))   # push id
    emit(b"\x8B\xCE")                           # mov ecx, esi  (нация)
    emit(call_rel(va, REGISTER_VA))              # call регистрации
    emit(b"\x8B\xCE")                           # mov ecx, esi
    emit(call_rel(va, REGISTER_VA))              # исходный вызов (id 130487, ступень 1)
    emit(jmp_rel(va, RETURN_VA))                 # назад в функцию России
    if len(code) > STUB_SPACE:
        raise SystemExit(f"код не влезает: {len(code)} > {STUB_SPACE}")
    return bytes(code)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compute_checksum(blob: bytes | bytearray) -> int:
    """Считать контрольную сумму PE так, как это делает Windows."""
    pe_off = struct.unpack_from("<I", blob, 0x3C)[0]
    opt_off = pe_off + 24
    check_off = opt_off + 64
    work = bytearray(blob)
    struct.pack_into("<I", work, check_off, 0)
    total = 0
    for i in range(0, len(work), 2):
        word = work[i] | (work[i + 1] << 8 if i + 1 < len(work) else 0)
        total += word
        total = (total & 0xFFFF) + (total >> 16)
    total = (total & 0xFFFF) + (total >> 16)
    return (total + len(work)) & 0xFFFFFFFF


def update_checksum(blob: bytearray) -> None:
    """Пересчитать контрольную сумму — только если в исходнике она была верной.

    Windows не проверяет это поле у обычных программ, но если в исходном файле
    она уже была неверной (у пересобранных сборок бывает), лезть в неё незачем:
    так откат возвращает файл байт в байт.
    """
    stored = struct.unpack_from("<I", blob, struct.unpack_from("<I", blob, 0x3C)[0] + 24 + 64)[0]
    if stored != compute_checksum(blob):
        return
    pe_off = struct.unpack_from("<I", blob, 0x3C)[0]
    check_off = pe_off + 24 + 64
    struct.pack_into("<I", blob, check_off, 0)
    struct.pack_into("<I", blob, check_off, compute_checksum(blob))


def patch(src: Path, dst: Path, dry_run: bool = False) -> None:
    blob = bytearray(src.read_bytes())
    print(f"источник: {src} ({len(blob):,} байт, sha256 {sha256(bytes(blob))[:16]}…)")

    if blob[HOOK_RAW:HOOK_RAW + 5] != ORIGINAL_HOOK:
        if blob[HOOK_RAW] == 0xE9:
            raise SystemExit("файл уже пропатчен — менять нечего")
        raise SystemExit(
            f"по смещению {HOOK_RAW} не тот код: ожидался call 0x{REGISTER_VA:x}, "
            f"а лежит {blob[HOOK_RAW:HOOK_RAW + 5].hex(' ')}. Это другая версия fm.exe."
        )
    if blob[STUB_RAW:STUB_RAW + STUB_SPACE] != b"\x90" * STUB_SPACE:
        raise SystemExit("место под код в .cave занято — другая сборка exe")

    stub = build_stub()
    comp_id, tier, name = SECOND_DIVISION
    print("\nродительская регистрация:")
    print(f"   ступень {tier}  id={comp_id:<9} {name}")
    print(f"\nкод-перехватчик: {len(stub)} байт по смещению {hex(STUB_RAW)}")
    print(f"перехват: {hex(HOOK_RAW)} -> jmp {hex(STUB_VA)}, возврат в {hex(RETURN_VA)}")

    blob[STUB_RAW:STUB_RAW + len(stub)] = stub
    blob[HOOK_RAW:HOOK_RAW + 5] = jmp_rel(HOOK_VA, STUB_VA)
    update_checksum(blob)

    if dry_run:
        print("\n--dry-run: файлы не записаны")
        return

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(bytes(blob))
    print(f"\nзаписано: {dst} ({len(blob):,} байт, sha256 {sha256(bytes(blob))[:16]}…)")


def revert(src: Path, dst: Path) -> None:
    blob = bytearray(src.read_bytes())
    if blob[HOOK_RAW] != 0xE9:
        raise SystemExit("этот файл не пропатчен — откатывать нечего")
    blob[HOOK_RAW:HOOK_RAW + 5] = ORIGINAL_HOOK
    blob[STUB_RAW:STUB_RAW + STUB_SPACE] = b"\x90" * STUB_SPACE
    update_checksum(blob)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(bytes(blob))
    print(f"откат выполнен: {dst} (sha256 {sha256(bytes(blob))[:16]}…)")


def verify(path: Path) -> None:
    """Проверка: PE читается, на месте перехват, код-перехватчик разбирается."""
    import capstone
    import pefile

    data = path.read_bytes()
    pe = pefile.PE(str(path), fast_load=True)
    print(f"\nпроверка {path.name}: PE ок, секций {pe.FILE_HEADER.NumberOfSections}, "
          f"точка входа {hex(pe.OPTIONAL_HEADER.AddressOfEntryPoint)}")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = False
    print("  код в .cave:")
    for ins in md.disasm(data[STUB_RAW:STUB_RAW + 200], STUB_VA):
        if ins.address - STUB_VA >= len(build_stub()):
            break
        print(f"    {ins.address:08x}  {ins.mnemonic:<7} {ins.op_str}")
    print("  место перехвата:")
    for ins in md.disasm(data[HOOK_RAW:HOOK_RAW + 5], HOOK_VA):
        print(f"    {ins.address:08x}  {ins.mnemonic:<7} {ins.op_str}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Патч fm.exe: Второй дивизион России")
    ap.add_argument("exe", help="файл fm.exe")
    ap.add_argument("--out", help="куда записать результат (по умолчанию рядом)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--revert", action="store_true", help="снять патч")
    ap.add_argument("--verify", action="store_true", help="только проверить файл")
    args = ap.parse_args()

    src = Path(args.exe)
    if not src.exists():
        raise SystemExit(f"нет файла {src}")
    dst = Path(args.out) if args.out else src.with_name(src.stem + "-patched.exe")

    if args.verify:
        verify(src)
        return
    if args.revert:
        revert(src, dst)
        return

    patch(src, dst, dry_run=args.dry_run)
    if not args.dry_run:
        verify(dst)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"ошибка: {exc}", file=sys.stderr)
        raise SystemExit(1)
