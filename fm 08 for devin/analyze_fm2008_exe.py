#!/usr/bin/env python3
"""Create reproducible static inventories for a PE executable (read-only input).

Requires: Python 3.9+ and pefile (pip install pefile).
The script never writes to or patches the input executable.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import hashlib
import json
import re
import struct
from pathlib import Path

import pefile

RTTI_RE = re.compile(rb"\.\?AV[^\x00]{1,512}?@@")
ASCII_RE = re.compile(rb"[\x20-\x7e]{4,}")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def csv_writer(path: Path, fields: list[str]):
    f = path.open("w", newline="", encoding="utf-8")
    w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    return f, w


def section_name(section) -> str:
    return section.Name.rstrip(b"\0").decode("ascii", "replace")


def rva_to_file_offset(pe: pefile.PE, rva: int) -> int | None:
    try:
        return pe.get_offset_from_rva(rva)
    except (pefile.PEFormatError, TypeError):
        return None


def resource_rows(pe: pefile.PE):
    rows = []
    if not hasattr(pe, "DIRECTORY_ENTRY_RESOURCE"):
        return rows

    def walk(directory, path):
        for entry in directory.entries:
            ident = entry.name.string.decode("utf-8", "replace") if getattr(entry, "name", None) else entry.struct.Id
            next_path = path + [str(ident)]
            directory = getattr(entry, "directory", None)
            data_entry = getattr(entry, "data", None)
            if directory is not None:
                walk(directory, next_path)
            elif data_entry is not None:
                data = data_entry.struct
                rva = data.OffsetToData
                rows.append({
                    "resource_path": "/".join(next_path),
                    "rva": f"0x{rva:08x}",
                    "file_offset": (f"0x{rva_to_file_offset(pe, rva):08x}"
                                    if rva_to_file_offset(pe, rva) is not None else ""),
                    "size": data.Size,
                    "codepage": data.CodePage,
                })
    walk(pe.DIRECTORY_ENTRY_RESOURCE, [])
    return rows


def jmp_candidates(pe: pefile.PE, blob: bytes):
    """Find raw E9 rel32 byte patterns in .text whose target lies in .cave.

    These are candidates rather than a full disassembly/xref proof; callers should
    inspect instruction boundaries and surrounding control flow independently.
    """
    text = next((s for s in pe.sections if section_name(s) == ".text"), None)
    cave = next((s for s in pe.sections if section_name(s) == ".cave"), None)
    if text is None or cave is None:
        return []
    start = text.PointerToRawData
    end = min(start + text.SizeOfRawData, len(blob))
    text_va = pe.OPTIONAL_HEADER.ImageBase + text.VirtualAddress
    cave_lo = pe.OPTIONAL_HEADER.ImageBase + cave.VirtualAddress
    cave_hi = cave_lo + max(cave.Misc_VirtualSize, cave.SizeOfRawData)
    rows = []
    pos = start
    while True:
        pos = blob.find(b"\xe9", pos, end - 4)
        if pos < 0:
            break
        site = text_va + pos - start
        target = (site + 5 + struct.unpack_from("<i", blob, pos + 1)[0]) & 0xffffffff
        if cave_lo <= target < cave_hi:
            rows.append({"source_va": f"0x{site:08x}", "target_va": f"0x{target:08x}",
                         "source_file_offset": f"0x{pos:08x}", "opcode": "E9 rel32"})
        pos += 1
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("--out", type=Path, required=True, help="directory for generated inventories")
    args = parser.parse_args()
    source = args.executable.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    blob = source.read_bytes()
    pe = pefile.PE(str(source), fast_load=False)

    stamp = pe.FILE_HEADER.TimeDateStamp
    summary = {
        "input_path_at_generation": str(source),
        "file_size_bytes": len(blob),
        "sha256": hashlib.sha256(blob).hexdigest(),
        "md5": hashlib.md5(blob).hexdigest(),
        "pe32_plus": bool(pe.OPTIONAL_HEADER.Magic == 0x20b),
        "machine": f"0x{pe.FILE_HEADER.Machine:04x}",
        "machine_name": "i386" if pe.FILE_HEADER.Machine == 0x14c else "see IMAGE_FILE_MACHINE",
        "timestamp_unix": stamp,
        "timestamp_utc": dt.datetime.fromtimestamp(stamp, dt.timezone.utc).isoformat(),
        "characteristics": f"0x{pe.FILE_HEADER.Characteristics:04x}",
        "subsystem": pe.OPTIONAL_HEADER.Subsystem,
        "image_base": f"0x{pe.OPTIONAL_HEADER.ImageBase:08x}",
        "entry_rva": f"0x{pe.OPTIONAL_HEADER.AddressOfEntryPoint:08x}",
        "entry_va": f"0x{pe.OPTIONAL_HEADER.ImageBase + pe.OPTIONAL_HEADER.AddressOfEntryPoint:08x}",
        "size_of_image": f"0x{pe.OPTIONAL_HEADER.SizeOfImage:08x}",
        "size_of_headers": f"0x{pe.OPTIONAL_HEADER.SizeOfHeaders:08x}",
        "checksum_field": f"0x{pe.OPTIONAL_HEADER.CheckSum:08x}",
        "dll_characteristics": f"0x{pe.OPTIONAL_HEADER.DllCharacteristics:04x}",
        "number_of_sections": pe.FILE_HEADER.NumberOfSections,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    f, w = csv_writer(out / "sections.csv", ["name", "rva", "virtual_size", "raw_offset", "raw_size", "characteristics"])
    with f:
        for s in pe.sections:
            w.writerow({"name": section_name(s), "rva": f"0x{s.VirtualAddress:08x}",
                        "virtual_size": f"0x{s.Misc_VirtualSize:08x}",
                        "raw_offset": f"0x{s.PointerToRawData:08x}",
                        "raw_size": f"0x{s.SizeOfRawData:08x}",
                        "characteristics": f"0x{s.Characteristics:08x}"})

    f, w = csv_writer(out / "directories.csv", ["index", "name", "rva", "size", "file_offset"])
    with f:
        for i, d in enumerate(pe.OPTIONAL_HEADER.DATA_DIRECTORY):
            # IMAGE_DIRECTORY_ENTRY_SECURITY is the sole directory whose address is a file offset.
            off = (d.VirtualAddress if i == 4 else
                   (rva_to_file_offset(pe, d.VirtualAddress) if d.VirtualAddress else None))
            w.writerow({"index": i, "name": d.name, "rva": f"0x{d.VirtualAddress:08x}",
                        "size": f"0x{d.Size:08x}",
                        "file_offset": f"0x{off:08x}" if off is not None else "(file-offset directory or absent)"})

    f, w = csv_writer(out / "imports.csv", ["dll", "name", "ordinal", "hint", "iat_rva", "iat_va"])
    with f:
        for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
            dll = entry.dll.decode("ascii", "replace")
            for imp in entry.imports:
                w.writerow({"dll": dll,
                            "name": imp.name.decode("ascii", "replace") if imp.name else "",
                            "ordinal": imp.ordinal if imp.name is None else "",
                            "hint": imp.hint if imp.name else "",
                            "iat_rva": f"0x{imp.address - pe.OPTIONAL_HEADER.ImageBase:08x}",
                            "iat_va": f"0x{imp.address:08x}"})

    f, w = csv_writer(out / "exports.csv", ["ordinal", "name", "rva", "va", "forwarder"])
    with f:
        for exp in getattr(getattr(pe, "DIRECTORY_ENTRY_EXPORT", None), "symbols", []):
            w.writerow({"ordinal": exp.ordinal,
                        "name": exp.name.decode("ascii", "replace") if exp.name else "",
                        "rva": f"0x{exp.address:08x}",
                        "va": f"0x{pe.OPTIONAL_HEADER.ImageBase + exp.address:08x}",
                        "forwarder": exp.forwarder.decode("ascii", "replace") if exp.forwarder else ""})

    f, w = csv_writer(out / "resources.csv", ["resource_path", "rva", "file_offset", "size", "codepage"])
    with f:
        for row in resource_rows(pe):
            w.writerow(row)

    rtti_matches = list(RTTI_RE.finditer(blob))
    rtti = sorted({m.group().decode("ascii", "replace") for m in rtti_matches})
    (out / "rtti_type_names.txt").write_text("\n".join(rtti) + "\n", encoding="utf-8")

    # Complete GNU-strings-like printable ASCII run inventory; offsets are file offsets.
    with gzip.open(out / "strings_ascii.tsv.gz", "wt", encoding="utf-8", newline="") as f:
        f.write("file_offset\ttext\n")
        for m in ASCII_RE.finditer(blob):
            f.write(f"0x{m.start():08x}\t{m.group().decode('ascii')}\n")

    f, w = csv_writer(out / "cave_jmp_candidates.csv", ["source_va", "target_va", "source_file_offset", "opcode"])
    with f:
        for row in jmp_candidates(pe, blob):
            w.writerow(row)

    # Compact, high-value cross-reference string list for quick handoff.
    key_tokens = (b"PERSON_SEARCH_PANEL", b"SCOUT_SEARCH_PERSON_FILTER",
                  b"PLAYER_SEARCH_FILTER_ADVISOR", b"Well-known players in your region",
                  b"Attempting to assign scout to a non-scout search", b"SIM_STATS")
    f, w = csv_writer(out / "key_strings.csv", ["file_offset", "text"])
    with f:
        for m in ASCII_RE.finditer(blob):
            if any(token.lower() in m.group().lower() for token in key_tokens):
                w.writerow({"file_offset": f"0x{m.start():08x}", "text": m.group().decode("ascii")})

    counts = {
        "imports": sum(1 for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []) for _imp in entry.imports),
        "named_exports": len(getattr(getattr(pe, "DIRECTORY_ENTRY_EXPORT", None), "symbols", [])),
        "rtti_matching_records": len(rtti_matches),
        "rtti_unique_names": len(rtti),
        "ascii_printable_runs_min_4": sum(1 for _ in ASCII_RE.finditer(blob)),
        "cave_jmp_byte_pattern_candidates": len(jmp_candidates(pe, blob)),
        "resource_data_entries": len(resource_rows(pe)),
    }
    (out / "counts.json").write_text(json.dumps(counts, indent=2) + "\n", encoding="utf-8")
    pe.close()
    print(json.dumps({"source": str(source), "out": str(out), "counts": counts}, indent=2))


if __name__ == "__main__":
    main()
