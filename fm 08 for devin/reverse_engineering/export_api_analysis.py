#!/usr/bin/env python3
"""Conservative static inventory of PE exports and their initial x86 code blocks.

The script groups names sharing an export VA and disassembles each unique entry
linearly only until its first RET (or a 0x400-byte cap). This is not a function
boundary recovery or a complete control-flow/call-graph analysis.
Requires Capstone: python -m pip install capstone
"""
from __future__ import annotations

import argparse
import csv
import struct
from collections import Counter, defaultdict
from pathlib import Path

MAX_BLOCK = 0x400


def read_pe(path: Path) -> tuple[bytes, int, list[dict[str, int | str]]]:
    data = path.read_bytes()
    if data[:2] != b"MZ":
        raise ValueError("input is not an MZ/PE file")
    pe_off = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe_off:pe_off + 4] != b"PE\0\0":
        raise ValueError("invalid PE signature")
    coff = pe_off + 4
    section_count = struct.unpack_from("<H", data, coff + 2)[0]
    optional_size = struct.unpack_from("<H", data, coff + 16)[0]
    optional = coff + 20
    magic = struct.unpack_from("<H", data, optional)[0]
    if magic != 0x10B:
        raise ValueError(f"expected PE32, got optional-header magic 0x{magic:x}")
    image_base = struct.unpack_from("<I", data, optional + 28)[0]
    section_table = optional + optional_size
    sections = []
    for i in range(section_count):
        off = section_table + i * 40
        raw_name = data[off:off + 8].split(b"\0", 1)[0]
        name = raw_name.decode("ascii", "replace")
        virtual_size, rva, raw_size, raw_ptr = struct.unpack_from("<IIII", data, off + 8)
        sections.append({"name": name, "rva": rva, "virtual_size": virtual_size,
                         "raw_size": raw_size, "raw_ptr": raw_ptr})
    return data, image_base, sections


def va_to_file_offset(va: int, image_base: int, sections: list[dict[str, int | str]]) -> tuple[int, str]:
    rva = va - image_base
    for sec in sections:
        start = int(sec["rva"])
        raw_size = int(sec["raw_size"])
        if start <= rva < start + raw_size:
            return int(sec["raw_ptr"]) + rva - start, str(sec["name"])
    raise ValueError(f"VA 0x{va:08x} is not backed by raw section bytes")


def csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def analyze(exe: Path, exports_csv: Path, out: Path) -> None:
    try:
        from capstone import Cs, CS_ARCH_X86, CS_MODE_32
    except ImportError as exc:
        raise SystemExit("Capstone required: python -m pip install capstone") from exc

    data, image_base, sections = read_pe(exe)
    exports = csv_rows(exports_csv)
    names_by_va: dict[int, list[str]] = defaultdict(list)
    for row in exports:
        if row.get("forwarder"):
            continue
        names_by_va[int(row["va"], 16)].append(row["name"])

    md = Cs(CS_ARCH_X86, CS_MODE_32)
    md.detail = True
    entries = []
    raw_by_va: dict[int, dict[str, str | int]] = {}
    for va, names in sorted(names_by_va.items()):
        file_off, section = va_to_file_offset(va, image_base, sections)
        chunk = data[file_off:file_off + MAX_BLOCK]
        insns = []
        direct_calls = []
        first_ret_bytes = ""
        first_ret = ""
        for ins in md.disasm(chunk, va):
            insns.append(ins)
            if ins.mnemonic == "call" and ins.operands and ins.operands[0].type == 2:
                direct_calls.append(f"0x{ins.operands[0].imm:08x}")
            if ins.mnemonic.startswith("ret"):
                first_ret = ins.mnemonic + (" " + ins.op_str if ins.op_str else "")
                first_ret_bytes = f"0x{ins.address + ins.size - va:x}"
                break
        first = insns[0] if insns else None
        row = {
            "entry_va": f"0x{va:08x}",
            "file_offset": f"0x{file_off:08x}",
            "section": section,
            "export_names": " | ".join(sorted(names)),
            "name_count_at_entry": str(len(names)),
            "first_bytes_hex": data[file_off:file_off + 16].hex(" "),
            "first_instruction": (first.mnemonic + (" " + first.op_str if first.op_str else "")) if first else "undecoded",
            "starts_with_ret": "yes" if first and first.mnemonic.startswith("ret") else "no",
            "linear_bytes_to_first_ret": first_ret_bytes or "not found within cap",
            "first_ret_instruction": first_ret or "not found within cap",
            "direct_call_targets_before_first_ret": " | ".join(direct_calls),
            "direct_call_count_before_first_ret": str(len(direct_calls)),
        }
        entries.append(row)
        raw_by_va[va] = row

    out.mkdir(parents=True, exist_ok=True)
    fields = list(entries[0]) if entries else []
    with (out / "export_entrypoints.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(entries)

    alias_rows = []
    for va, names in sorted(names_by_va.items()):
        alias_rows.append({"entry_va": f"0x{va:08x}", "name_count": str(len(names)),
                           "export_names": " | ".join(sorted(names)),
                           "starts_with_ret": raw_by_va[va]["starts_with_ret"],
                           "file_offset": raw_by_va[va]["file_offset"]})
    with (out / "export_name_groups.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(alias_rows[0]))
        writer.writeheader()
        writer.writerows(alias_rows)

    suffix_counts: Counter[str] = Counter()
    suffix_entries: dict[str, set[int]] = defaultdict(set)
    suffix_ret_entries: dict[str, set[int]] = defaultdict(set)
    suffix_shared_entries: dict[str, set[int]] = defaultdict(set)
    for row in exports:
        if row.get("forwarder"):
            continue
        va = int(row["va"], 16)
        suffix = row["name"].rsplit("_", 1)[-1]
        suffix_counts[suffix] += 1
        suffix_entries[suffix].add(va)
        if raw_by_va[va]["starts_with_ret"] == "yes":
            suffix_ret_entries[suffix].add(va)
        if len(names_by_va[va]) > 1:
            suffix_shared_entries[suffix].add(va)
    families = []
    for suffix, count in sorted(suffix_counts.items(), key=lambda x: (-x[1], x[0])):
        families.append({"name_suffix_heuristic": suffix,
                         "export_name_count": str(count),
                         "unique_entry_count": str(len(suffix_entries[suffix])),
                         "entries_starting_with_ret": str(len(suffix_ret_entries[suffix])),
                         "entries_shared_by_multiple_names": str(len(suffix_shared_entries[suffix]))})
    with (out / "export_suffix_counts.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(families[0]))
        writer.writeheader()
        writer.writerows(families)

    print(f"{len(exports)} export names; {len(names_by_va)} distinct entry VAs; wrote {out}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--exports", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    analyze(args.exe, args.exports, args.out)


if __name__ == "__main__":
    main()
