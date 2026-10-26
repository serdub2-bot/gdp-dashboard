#!/usr/bin/env python3
"""exe_scan.py — что игра знает о соревнованиях: разбор таблиц в fm.exe.

В FM2008 набор играбельных дивизионов задан не в базе, а в самом exe: для
каждой страны есть функция, которая регистрирует дивизионы по порядку.

    push 0            ; третий аргумент
    push <номер>      ; ступень: 0, 1, 2, ...
    push <id соревнования>
    mov  ecx, <нация>
    call 0xd63c10     ; регистрация дивизиона

У Англии таких вызовов шесть (Премьер, Первый, Второй, Третий, Конференция...),
у России — два (Премьер и Первый). Второго дивизиона в списке нет, поэтому он
и не появляется в игре, что бы мы ни писали в базе.

Скрипт находит все такие регистрации, привязывает их к стране и печатает
таблицу. Плюс находит вторую таблицу (call 0xd35180) — там у соревнований
указано число команд и признак -2/-1.

Использование:
    python3 exe_scan.py --exe fm.exe --list            # все регистрации
    python3 exe_scan.py --exe fm.exe --nation Россия   # одна страна
    python3 exe_scan.py --exe fm.exe --compare         # таблица vs таблица
"""
from __future__ import annotations

import argparse
import struct
from pathlib import Path

import capstone

REGISTER_TIER = 0xD63C10   # регистрация дивизиона: (id, ступень, 0)
REGISTER_INFO = 0xD35180   # сведения: (id, ?, команд, признак, 0, 0)
IMAGE_BASE = 0x400000


def load_text(path: Path) -> tuple[bytes, int, int]:
    """Вернуть (.text как есть, файловое смещение, виртуальный адрес)."""
    blob = path.read_bytes()
    pe = blob.find(b"PE\0\0")
    if pe < 0:
        raise SystemExit("это не PE-файл")
    nsec = struct.unpack_from("<H", blob, pe + 6)[0]
    opt_size = struct.unpack_from("<H", blob, pe + 20)[0]
    sec = pe + 24 + opt_size
    for i in range(nsec):
        off = sec + i * 40
        name = blob[off: off + 8].rstrip(b"\0").decode("latin-1")
        vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", blob, off + 8)
        if name == ".text":
            return blob[rawptr: rawptr + rawsize], rawptr, vaddr
    raise SystemExit("нет секции .text")


def scan(text: bytes, raw_base: int, va_base: int, targets: dict[int, str]) -> dict:
    """Линейный проход по .text: собрать вызовы с аргументами из push."""
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = False
    md.skipdata = True
    result: dict[int, list[dict]] = {t: [] for t in targets}
    pending: list[int] = []
    KEEP = ("mov", "lea", "movzx", "movsx", "test", "cmp", "xor", "push")

    for ins in md.disasm(text, va_base + IMAGE_BASE):
        raw = ins.address - IMAGE_BASE - va_base + raw_base
        mnem = ins.mnemonic
        if mnem == "push":
            op = ins.op_str
            value = None
            if op.startswith("0x"):
                value = int(op, 16)
            elif op.lstrip("-").isdigit():
                value = int(op) & 0xFFFFFFFF
            pending.append(value if value is not None else -1)
            if len(pending) > 8:
                pending.pop(0)
        elif mnem == "call":
            try:
                target = int(ins.op_str, 16)
            except ValueError:
                target = -1
            if target in targets:
                result[target].append({"raw": raw, "va": ins.address,
                                       "args": [a for a in pending if a >= 0]})
            pending = []
        elif not mnem.startswith(KEEP):
            pending = []
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default="fm.exe")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--nation", help="показать только одну страну (по префиксу названия)")
    ap.add_argument("--db", help="папка db — чтобы подписать id названиями")
    ap.add_argument("--tiers", help="файл JSON: id -> ступень (для справки)")
    args = ap.parse_args()

    text, raw_base, va_base = load_text(Path(args.exe))
    print(f".text: {len(text):,} байт, файловое смещение {hex(raw_base)}")

    calls = scan(text, raw_base, va_base,
                 {REGISTER_TIER: "tier", REGISTER_INFO: "info"})
    print(f"регистраций дивизионов: {len(calls[REGISTER_TIER])}")
    print(f"записей со сведениями:  {len(calls[REGISTER_INFO])}")

    names: dict[int, str] = {}
    if args.db:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from hunt import lang_blob, list_competitions
        names = {i["id"]: i["name"] for i in
                 list_competitions(lang_blob(Path(args.db)), "")}

    for call in calls[REGISTER_TIER]:
        a = call["args"]
        if len(a) < 3 or None in a[:3]:
            continue
        comp, tier, _ = a[-1], a[-2], a[-3]
        title = names.get(comp, "")
        if args.nation and not title.startswith(args.nation):
            continue
        print(f"  @{call['raw']:<9} ступень={tier:<4} id={comp:<10} {title}")


if __name__ == "__main__":
    main()
