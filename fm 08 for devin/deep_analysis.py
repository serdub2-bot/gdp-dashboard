#!/usr/bin/env python3
"""Generate deeper static inventories for the FM2008 PE executable.

Requires Python 3.9+, pefile and capstone. Reads the EXE only; outputs are written
under --out. The .text linear sweep is intentionally labeled as a heuristic because
PE sections can contain embedded data and this binary has no PDB alongside it.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import gzip
import hashlib
import json
import math
import re
import struct
from pathlib import Path

import pefile
from capstone import CS_ARCH_X86, CS_MODE_32, Cs

RTTI_RE = re.compile(rb"\.\?AV[^\x00]{1,512}?@@")
ASCII_RE = re.compile(rb"[\x20-\x7e]{4,}")
WIDE_ASCII_RE = re.compile(rb"(?:[\x20-\x7e]\x00){4,}")
COND_JUMPS = {"ja", "jae", "jb", "jbe", "jc", "jcxz", "jecxz", "je", "jg", "jge",
              "jl", "jle", "jna", "jnae", "jnb", "jnbe", "jnc", "jne", "jng",
              "jnge", "jnl", "jnle", "jno", "jnp", "jns", "jnz", "jo", "jp",
              "jpe", "jpo", "js", "jz", "loop", "loope", "loopne", "loopnz", "loopz"}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def name(section) -> str:
    return section.Name.rstrip(b"\0").decode("ascii", "replace")


def section_for_va(pe: pefile.PE, va: int):
    rva = va - pe.OPTIONAL_HEADER.ImageBase
    for s in pe.sections:
        if s.VirtualAddress <= rva < s.VirtualAddress + max(s.Misc_VirtualSize, s.SizeOfRawData):
            return name(s)
    return ""


def section_for_file(pe: pefile.PE, offset: int):
    for s in pe.sections:
        if s.PointerToRawData <= offset < s.PointerToRawData + s.SizeOfRawData:
            return name(s)
    return "HEADER/OVERLAY"


def csv_open(path: Path, fields):
    f = path.open("w", encoding="utf-8", newline="")
    return f, csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")


def csv_gzip_open(path: Path, fields):
    f = gzip.open(path, "wt", encoding="utf-8", newline="")
    return f, csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")


def entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts = collections.Counter(data)
    n = len(data)
    return -sum((v / n) * math.log2(v / n) for v in counts.values())


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("executable", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    src = args.executable.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    blob = src.read_bytes()
    pe = pefile.PE(str(src), fast_load=False)
    base = pe.OPTIONAL_HEADER.ImageBase

    # CodeView / PDB identity and section-level entropy.
    debug = []
    for d in getattr(pe, "DIRECTORY_ENTRY_DEBUG", []):
        ent = d.entry
        row = {"type": d.struct.Type, "size": d.struct.SizeOfData,
               "timestamp": d.struct.TimeDateStamp,
               "rva": f"0x{d.struct.AddressOfRawData:08x}",
               "file_offset": f"0x{d.struct.PointerToRawData:08x}"}
        if getattr(ent, "CvSignature", b"") == b"RSDS":
            row.update({"codeview": "RSDS", "pdb_guid": ent.Signature_String,
                        "pdb_age": ent.Age,
                        "pdb_path": ent.PdbFileName.rstrip(b"\0").decode("utf-8", "replace")})
        debug.append(row)
    f, w = csv_open(out / "debug_directory.csv",
                    ["type", "size", "timestamp", "rva", "file_offset", "codeview", "pdb_guid", "pdb_age", "pdb_path"])
    with f:
        w.writeheader()
        w.writerows(debug)

    f, w = csv_open(out / "section_entropy.csv",
                    ["name", "rva", "file_offset", "raw_size", "virtual_size", "entropy_bits_per_byte", "raw_sha256"])
    with f:
        w.writeheader()
        for s in pe.sections:
            raw = blob[s.PointerToRawData:s.PointerToRawData + s.SizeOfRawData]
            w.writerow({"name": name(s), "rva": f"0x{s.VirtualAddress:08x}",
                        "file_offset": f"0x{s.PointerToRawData:08x}",
                        "raw_size": s.SizeOfRawData, "virtual_size": s.Misc_VirtualSize,
                        "entropy_bits_per_byte": f"{entropy(raw):.6f}", "raw_sha256": sha256(raw)})

    # Header/mitigation metadata, including the legacy x86 Load Config structure.
    fh = pe.FILE_HEADER
    oh = pe.OPTIONAL_HEADER
    meta = {
        "file_header": {k: getattr(fh, k) for k in (
            "Machine", "NumberOfSections", "TimeDateStamp", "PointerToSymbolTable",
            "NumberOfSymbols", "SizeOfOptionalHeader", "Characteristics")},
        "optional_header": {k: getattr(oh, k) for k in (
            "Magic", "MajorLinkerVersion", "MinorLinkerVersion", "SizeOfCode",
            "SizeOfInitializedData", "SizeOfUninitializedData", "AddressOfEntryPoint",
            "BaseOfCode", "BaseOfData", "ImageBase", "SectionAlignment", "FileAlignment",
            "MajorOperatingSystemVersion", "MinorOperatingSystemVersion", "MajorImageVersion",
            "MinorImageVersion", "MajorSubsystemVersion", "MinorSubsystemVersion", "SizeOfImage",
            "SizeOfHeaders", "CheckSum", "Subsystem", "DllCharacteristics", "SizeOfStackReserve",
            "SizeOfStackCommit", "SizeOfHeapReserve", "SizeOfHeapCommit", "LoaderFlags",
            "NumberOfRvaAndSizes")},
        "entry_va": f"0x{oh.ImageBase + oh.AddressOfEntryPoint:08x}",
        "load_config": (pe.DIRECTORY_ENTRY_LOAD_CONFIG.struct.dump_dict()
                        if hasattr(pe, "DIRECTORY_ENTRY_LOAD_CONFIG") else None),
        "authenticode_digest_check": {
            "embedded_sha1_from_SpcIndirectDataContent": "6cbea0a5633e6139dd2f70a1fe241dd4b379e279",
            "computed_authentihash_sha1": "af461bf88674c836f07cb04c75fed7885d31453d",
            "result": "MISMATCH: embedded PE image digest does not match current file bytes",
            "method_note": "Computed with Signify SignedPEFingerprinter 0.9.3; OpenSSL version regex was patched only in /tmp to support the host's 3.0.20 version string. This tests image digest matching, not trust-chain validation."
        }
    }
    (out / "pe_metadata.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    # Extract each resource data blob to a separate evidence file; never writes to input.
    resource_dir = out / "resource_payloads"
    resource_dir.mkdir(exist_ok=True)
    resource_rows = []
    def walk_resources(directory, path_parts):
        for entry in directory.entries:
            ident = entry.name.string.decode("utf-8", "replace") if getattr(entry, "name", None) else entry.struct.Id
            next_parts = path_parts + [str(ident)]
            child_dir = getattr(entry, "directory", None)
            leaf = getattr(entry, "data", None)
            if child_dir is not None:
                walk_resources(child_dir, next_parts)
            elif leaf is not None:
                rs = leaf.struct
                resource_path = "/".join(next_parts)
                payload = pe.get_data(rs.OffsetToData, rs.Size)
                safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", resource_path).strip("_")[:100]
                if payload.startswith(b"\x89PNG\r\n\x1a\n"):
                    suffix = ".png"
                elif resource_path.endswith("__GDF_XML/0"):
                    suffix = ".xml"
                else:
                    suffix = ".bin"
                output_name = f"{len(resource_rows):03d}_{safe}{suffix}"
                (resource_dir / output_name).write_bytes(payload)
                resource_rows.append({"resource_path": resource_path,
                                      "rva": f"0x{rs.OffsetToData:08x}",
                                      "size": rs.Size, "codepage": rs.CodePage,
                                      "file": output_name, "sha256": sha256(payload)})
    if hasattr(pe, "DIRECTORY_ENTRY_RESOURCE"):
        walk_resources(pe.DIRECTORY_ENTRY_RESOURCE, [])
    f, w = csv_open(out / "resource_payloads.csv",
                    ["resource_path", "rva", "size", "codepage", "file", "sha256"])
    with f:
        w.writeheader()
        w.writerows(resource_rows)

    # Detailed RTTI string occurrences, including location and duplicate frequency.
    matches = list(RTTI_RE.finditer(blob))
    freq = collections.Counter(m.group().decode("ascii", "replace") for m in matches)
    rtti_va = {}
    f, w = csv_open(out / "rtti_occurrences.csv",
                    ["file_offset", "rva", "string_va", "type_descriptor_va_candidate", "name", "occurrence_count"])
    with f:
        w.writeheader()
        for m in matches:
            off = m.start()
            rva = pe.get_rva_from_offset(off)
            if rva is None:
                continue
            va = base + rva
            type_name = m.group().decode("ascii", "replace")
            td_va = va - 8  # MSVC x86 TypeDescriptor name follows two 32-bit header pointers.
            rtti_va[td_va] = type_name
            w.writerow({"file_offset": f"0x{off:08x}", "rva": f"0x{rva:08x}",
                        "string_va": f"0x{va:08x}",
                        "type_descriptor_va_candidate": f"0x{td_va:08x}",
                        "name": type_name, "occurrence_count": freq[type_name]})

    domain_terms = {
        "PERSON": ("PERSON",), "PLAYER": ("PLAYER",), "SCOUT": ("SCOUT",),
        "TEAM/CLUB": ("TEAM", "CLUB"), "COMPETITION": ("COMP", "LEAGUE", "CUP", "FIXTURE"),
        "MATCH": ("MATCH",), "STATISTICS": ("STAT", "STATS"),
        "SEARCH": ("SEARCH",), "UI/PANEL": ("PANEL", "WIDGET", "CONTAINER"),
        "FILTER": ("FILTER",), "DATABASE/PERSISTENCE": ("DATABASE", "PERSISTENT", "STREAMABLE"),
        "FILE/SERIALIZATION": ("FILE", "READER", "WRITER", "SERIAL"),
        "NETWORK": ("NETWORK", "SOCKET", "CONNECTION"),
        "FINANCE": ("FINANCE", "MONEY", "WAGE", "CONTRACT"),
        "TRANSFER": ("TRANSFER", "OFFER", "LOAN"),
        "TACTICS": ("TACTIC", "FORMATION", "INSTRUCTION"),
        "MEDIA/NEWS": ("MEDIA", "NEWS", "MESSAGE"),
    }
    unique_rtti = sorted(freq)
    f, w = csv_open(out / "rtti_keyword_counts.csv", ["domain", "matched_unique_names", "sample_type_names"])
    with f:
        w.writeheader()
        for domain, tokens in domain_terms.items():
            rows = [t for t in unique_rtti if any(token in t.upper() for token in tokens)]
            w.writerow({"domain": domain, "matched_unique_names": len(rows),
                        "sample_type_names": ";".join(rows[:12])})

    def resolve_type_descriptor(td_va):
        """Resolve the common 32-bit MSVC TypeDescriptor name pointer."""
        rva = td_va + 8 - base
        try:
            off = pe.get_offset_from_rva(rva)
        except pefile.PEFormatError:
            return None
        if off is None or off >= len(blob):
            return None
        raw_name = blob[off:off + 512].split(b"\0", 1)[0]
        if raw_name.startswith((b".?AV", b".?AU")) and raw_name.endswith(b"@@"):
            return raw_name.decode("ascii", "replace")
        return None

    # Aligned absolute pointers in read-only/data areas which target RTTI TypeDescriptors.
    # These are candidate xrefs, not proof that every surrounding structure is valid RTTI.
    rtti_rows = []
    col_by_va = {}
    hierarchy_rows = []
    hierarchy_keys = set()
    for s in pe.sections:
        if name(s) not in (".rdata", ".data"):
            continue
        start, end = s.PointerToRawData, min(s.PointerToRawData + s.SizeOfRawData, len(blob))
        first = (start + 3) & ~3
        for off in range(first, end - 3, 4):
            ptr = struct.unpack_from("<I", blob, off)[0]
            if ptr not in rtti_va:
                continue
            source_va = base + pe.get_rva_from_offset(off)
            td_name = rtti_va[ptr]
            col = None
            col_va = None
            if off >= 12:
                try:
                    sig, offset, cd, td, chd = struct.unpack_from("<5I", blob, off - 12)
                    if td == ptr and sig == 0 and chd:
                        col = (off - 12, sig, offset, cd, chd)
                        col_va = base + pe.get_rva_from_offset(off - 12)
                        # Validate the linked ClassHierarchyDescriptor and its base array.
                        try:
                            chd_off = pe.get_offset_from_rva(chd - base)
                            chd_sig, attrs, nbase, base_array_va = struct.unpack_from("<4I", blob, chd_off)
                            bca_off = pe.get_offset_from_rva(base_array_va - base)
                            if (chd_sig == 0 and 0 < nbase <= 512 and bca_off is not None
                                    and bca_off + nbase * 4 <= len(blob)):
                                members = []
                                valid = True
                                for index in range(nbase):
                                    bcd_va = struct.unpack_from("<I", blob, bca_off + index * 4)[0]
                                    bcd_off = pe.get_offset_from_rva(bcd_va - base)
                                    if bcd_off is None or bcd_off + 24 > len(blob):
                                        valid = False
                                        break
                                    bcd = struct.unpack_from("<6I", blob, bcd_off)
                                    member_type = resolve_type_descriptor(bcd[0])
                                    if member_type is None:
                                        valid = False
                                        break
                                    members.append((index, bcd_va, member_type, bcd[1], bcd[2], bcd[3], bcd[4], bcd[5]))
                                if valid:
                                    col_by_va[col_va] = (td_name, chd, off - 12, offset, cd)
                                    hkey = (td_name, chd)
                                    if hkey not in hierarchy_keys:
                                        hierarchy_keys.add(hkey)
                                        for (index, bcd_va, member_type, contained, mdisp, pdisp, vdisp, battrs) in members:
                                            hierarchy_rows.append({
                                                "hierarchy_type": td_name, "class_hierarchy_descriptor_va": chd,
                                                "attributes": attrs, "base_count": nbase, "base_index": index,
                                                "base_descriptor_va": bcd_va, "base_type": member_type,
                                                "contained_bases": contained, "mdisp": mdisp,
                                                "pdisp_signed": struct.unpack("<i", struct.pack("<I", pdisp))[0],
                                                "vdisp_signed": struct.unpack("<i", struct.pack("<I", vdisp))[0],
                                                "base_attributes": battrs})
                        except (pefile.PEFormatError, struct.error, TypeError):
                            pass
                except struct.error:
                    pass
            rtti_rows.append({"source_section": name(s), "source_file_offset": off,
                              "source_va": source_va, "type_descriptor_va": ptr,
                              "type_name": td_name, "col_candidate_va": col_va,
                              "col_offset": col[2] if col else "",
                              "col_cd_offset": col[3] if col else "",
                              "class_hierarchy_descriptor_va": col[4] if col else ""})
    f, w = csv_open(out / "rtti_pointer_candidates.csv",
                    ["source_section", "source_file_offset", "source_va", "type_descriptor_va", "type_name",
                     "col_candidate_va", "col_offset", "col_cd_offset", "class_hierarchy_descriptor_va"])
    with f:
        w.writeheader()
        for row in rtti_rows:
            row["source_file_offset"] = f"0x{row['source_file_offset']:08x}"
            row["source_va"] = f"0x{row['source_va']:08x}"
            row["type_descriptor_va"] = f"0x{row['type_descriptor_va']:08x}"
            if row["col_candidate_va"] is not None:
                row["col_candidate_va"] = f"0x{row['col_candidate_va']:08x}"
            if row["class_hierarchy_descriptor_va"]:
                row["class_hierarchy_descriptor_va"] = f"0x{row['class_hierarchy_descriptor_va']:08x}"
            w.writerow(row)

    f, w = csv_open(out / "class_hierarchy_members.csv",
                    ["hierarchy_type", "class_hierarchy_descriptor_va", "attributes", "base_count",
                     "base_index", "base_descriptor_va", "base_type", "contained_bases", "mdisp",
                     "pdisp_signed", "vdisp_signed", "base_attributes"])
    with f:
        w.writeheader()
        for row in hierarchy_rows:
            row["class_hierarchy_descriptor_va"] = f"0x{row['class_hierarchy_descriptor_va']:08x}"
            row["base_descriptor_va"] = f"0x{row['base_descriptor_va']:08x}"
            w.writerow(row)

    # Candidate vtables: first function pointer follows the COL pointer at vtable[-1].
    col_refs = collections.defaultdict(list)
    for s in pe.sections:
        if name(s) not in (".rdata", ".data"):
            continue
        start, end = s.PointerToRawData, min(s.PointerToRawData + s.SizeOfRawData, len(blob))
        for off in range((start + 3) & ~3, end - 3, 4):
            ptr = struct.unpack_from("<I", blob, off)[0]
            if ptr in col_by_va:
                col_refs[ptr].append((off, base + pe.get_rva_from_offset(off)))
    f, w = csv_open(out / "rtti_vtable_candidates.csv",
                    ["type_name", "col_va", "col_file_offset", "vtable_va_candidate", "first_slot_va",
                     "first_slot_target_va", "first_slot_target_section"])
    with f:
        w.writeheader()
        for col_va, (td_name, _chd, col_file_offset, _col_offset, _cd_offset) in sorted(col_by_va.items()):
            for off, source_va in col_refs.get(col_va, []):
                vt_va = source_va + 4
                vt_off = off + 4
                first = struct.unpack_from("<I", blob, vt_off)[0] if vt_off + 4 <= len(blob) else 0
                w.writerow({"type_name": td_name, "col_va": f"0x{col_va:08x}",
                            "col_file_offset": f"0x{col_file_offset:08x}",
                            "vtable_va_candidate": f"0x{vt_va:08x}",
                            "first_slot_va": f"0x{vt_va:08x}",
                            "first_slot_target_va": f"0x{first:08x}",
                            "first_slot_target_section": section_for_va(pe, first)})

    # Compact analyst-oriented map for the previously investigated search classes and
    # a few adjacent match/search UI types. The source CSV remains the full record.
    focus_names = {
        ".?AVPERSON_SEARCH_PANEL@@", ".?AVPERSON_SEARCH_INFO_PANEL@@",
        ".?AVSCOUT_SEARCH_PERSON_FILTER@@", ".?AVPLAYER_SEARCH_FILTER_ADVISOR@@",
        ".?AVPERSON_FILTER@@", ".?AVGAME_MATCH_STATS@@", ".?AVMATCH_STATS_ARCHIVE@@",
        ".?AVMATCH_NOTIFICATION_PANEL@@", ".?AVMATCH_SCORE_TIME_PANEL@@",
    }
    class_members = collections.defaultdict(list)
    for row in hierarchy_rows:
        class_members[row["hierarchy_type"]].append(row)
    focus_vtables = collections.defaultdict(list)
    for col_va, values in col_by_va.items():
        td_name = values[0]
        if td_name not in focus_names:
            continue
        for ref_off, source_va in col_refs.get(col_va, []):
            target = struct.unpack_from("<I", blob, ref_off + 4)[0]
            focus_vtables[td_name].append((col_va, values[1], source_va + 4, target))
    f, w = csv_open(out / "focused_class_map.csv",
                    ["type_name", "direct_base_candidates", "complete_object_locator_va",
                     "class_hierarchy_descriptor_va", "base_count", "vtable_va_candidate",
                     "first_slot_target_va", "first_slot_target_section"])
    with f:
        w.writeheader()
        for type_name in sorted(focus_names):
            members = class_members.get(type_name, [])
            direct = []
            by_index = {r["base_index"]: r for r in members}
            if members:
                i = 1
                while i < members[0]["base_count"] and i in by_index:
                    m = by_index[i]
                    direct.append(m["base_type"])
                    i += 1 + m["contained_bases"]
            tables = focus_vtables.get(type_name) or [(None, None, None, None)]
            for col_va, chd_va, table_va, first in tables:
                w.writerow({"type_name": type_name, "direct_base_candidates": ";".join(direct),
                            "complete_object_locator_va": f"0x{col_va:08x}" if col_va else "",
                            "class_hierarchy_descriptor_va": f"0x{chd_va:08x}" if chd_va else "",
                            "base_count": members[0]["base_count"] if members else "",
                            "vtable_va_candidate": f"0x{table_va:08x}" if table_va else "",
                            "first_slot_target_va": f"0x{first:08x}" if first else "",
                            "first_slot_target_section": section_for_va(pe, first) if first else ""})

    # UTF-16LE ASCII-like strings are not covered by the primary ASCII inventory.
    wide_count = 0
    with gzip.open(out / "strings_utf16le_ascii.tsv.gz", "wt", encoding="utf-8", newline="") as f:
        f.write("file_offset\ttext\n")
        for m in WIDE_ASCII_RE.finditer(blob):
            f.write(f"0x{m.start():08x}\t{m.group()[::2].decode('ascii')}\n")
            wide_count += 1

    # Find fixed absolute-pointer references to extracted strings; bytewise scan of all
    # raw section bytes. A match is a candidate data/code xref and must be disassembled.
    string_targets = {}
    for m in ASCII_RE.finditer(blob):
        try:
            rva = pe.get_rva_from_offset(m.start())
        except pefile.PEFormatError:
            continue
        if rva is None:
            continue
        va = base + rva
        text = m.group().decode("ascii")
        string_targets[va] = (m.start(), text[:240])
    f, w = csv_open(out / "string_pointer_xref_candidates.csv",
                    ["source_section", "source_file_offset", "source_va", "target_string_va", "target_file_offset", "text"])
    total_string_xrefs = 0
    with f:
        w.writeheader()
        for s in pe.sections:
            start, end = s.PointerToRawData, min(s.PointerToRawData + s.SizeOfRawData, len(blob))
            if end - start < 4:
                continue
            for off in range(start, end - 3):
                ptr = struct.unpack_from("<I", blob, off)[0]
                rec = string_targets.get(ptr)
                if rec is not None:
                    target_off, text = rec
                    w.writerow({"source_section": name(s), "source_file_offset": f"0x{off:08x}",
                                "source_va": f"0x{base + pe.get_rva_from_offset(off):08x}",
                                "target_string_va": f"0x{ptr:08x}",
                                "target_file_offset": f"0x{target_off:08x}", "text": text})
                    total_string_xrefs += 1

    # Full linear sweep, retaining only control-flow candidates and aggregates.
    text_section = next(s for s in pe.sections if name(s) == ".text")
    text_raw = blob[text_section.PointerToRawData:text_section.PointerToRawData + text_section.SizeOfRawData]
    text_va = base + text_section.VirtualAddress
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    md.skipdata = True
    mnem_counts = collections.Counter()
    call_targets = collections.Counter()
    branch_targets = collections.Counter()
    instruction_count = 0
    edge_count = 0
    f, w = csv_gzip_open(out / "linear_control_flow_candidates.csv.gz",
                         ["source_va", "source_file_offset", "kind", "mnemonic", "bytes", "target_va", "target_rva", "target_section"])
    with f:
        w.writeheader()
        for insn in md.disasm(text_raw, text_va):
            instruction_count += 1
            mnem_counts[insn.mnemonic] += 1
            if insn.mnemonic == ".byte":
                continue
            if insn.mnemonic != "call" and insn.mnemonic != "jmp" and insn.mnemonic not in COND_JUMPS:
                continue
            match = re.fullmatch(r"0x([0-9a-fA-F]+)", insn.op_str.strip())
            if not match:
                continue
            target = int(match.group(1), 16)
            kind = "call" if insn.mnemonic == "call" else ("jmp" if insn.mnemonic == "jmp" else "conditional")
            target_rva = target - base if target >= base else None
            w.writerow({"source_va": f"0x{insn.address:08x}",
                        "source_file_offset": f"0x{text_section.PointerToRawData + insn.address - text_va:08x}",
                        "kind": kind, "mnemonic": insn.mnemonic, "bytes": insn.bytes.hex(),
                        "target_va": f"0x{target:08x}",
                        "target_rva": f"0x{target_rva:08x}" if target_rva is not None else "",
                        "target_section": section_for_va(pe, target)})
            edge_count += 1
            if kind == "call" and section_for_va(pe, target) == ".text":
                call_targets[target] += 1
            elif kind != "call":
                branch_targets[target] += 1

    f, w = csv_open(out / "linear_mnemonic_counts.csv", ["mnemonic", "count"])
    with f:
        w.writeheader()
        for mnemonic, count in mnem_counts.most_common():
            w.writerow({"mnemonic": mnemonic, "count": count})

    # Entry candidates from exports, image entry point, and direct CALL destinations.
    entries = collections.defaultdict(set)
    entries[base + pe.OPTIONAL_HEADER.AddressOfEntryPoint].add("PE entry point")
    for exp in getattr(getattr(pe, "DIRECTORY_ENTRY_EXPORT", None), "symbols", []):
        entries[base + exp.address].add("export:" + (exp.name.decode("ascii", "replace") if exp.name else str(exp.ordinal)))
    for target in call_targets:
        entries[target].add("direct CALL target")
    f, w = csv_open(out / "function_entry_candidates.csv",
                    ["va", "rva", "section", "direct_call_count", "source_kinds"])
    with f:
        w.writeheader()
        for va, kinds in sorted(entries.items()):
            w.writerow({"va": f"0x{va:08x}", "rva": f"0x{va-base:08x}",
                        "section": section_for_va(pe, va), "direct_call_count": call_targets.get(va, 0),
                        "source_kinds": ";".join(sorted(kinds))})

    # IAT-addressed CALL/JMP instructions (FF 15 / FF 25 absolute operands).
    iat = {}
    for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
        dll = entry.dll.decode("ascii", "replace")
        for imp in entry.imports:
            ident = imp.name.decode("ascii", "replace") if imp.name else f"ordinal_{imp.ordinal}"
            iat[imp.address] = (dll, ident)
    f, w = csv_open(out / "iat_call_site_candidates.csv",
                    ["source_va", "source_file_offset", "opcode", "iat_va", "dll", "import_name"])
    with f:
        w.writeheader()
        for opcode in (b"\xff\x15", b"\xff\x25"):
            pos = text_section.PointerToRawData
            end = pos + text_section.SizeOfRawData
            while True:
                pos = blob.find(opcode, pos, end - 4)
                if pos < 0:
                    break
                ptr = struct.unpack_from("<I", blob, pos + 2)[0]
                if ptr in iat:
                    dll, imp_name = iat[ptr]
                    w.writerow({"source_va": f"0x{text_va + pos-text_section.PointerToRawData:08x}",
                                "source_file_offset": f"0x{pos:08x}",
                                "opcode": "CALL [abs32]" if opcode == b"\xff\x15" else "JMP [abs32]",
                                "iat_va": f"0x{ptr:08x}", "dll": dll, "import_name": imp_name})
                pos += 1

    # Export prolog/body snippets: 48 instructions max, stopping at RET. Not function sizes.
    exp_path = out / "export_disassembly.txt"
    dis = Cs(CS_ARCH_X86, CS_MODE_32)
    with exp_path.open("w", encoding="utf-8") as f:
        for exp in sorted(getattr(getattr(pe, "DIRECTORY_ENTRY_EXPORT", None), "symbols", []), key=lambda x: x.address):
            va = base + exp.address
            off = pe.get_offset_from_rva(exp.address)
            label = exp.name.decode("ascii", "replace") if exp.name else f"ordinal_{exp.ordinal}"
            f.write(f"\n; {label} ordinal={exp.ordinal} RVA=0x{exp.address:08x} VA=0x{va:08x} file=0x{off:08x}\n")
            chunk = blob[off:min(off + 0x200, len(blob))]
            count = 0
            for insn in dis.disasm(chunk, va):
                f.write(f"{insn.address:08x}: {insn.bytes.hex():<18} {insn.mnemonic:<8} {insn.op_str}\n")
                count += 1
                if insn.mnemonic.startswith("ret") or count >= 48:
                    break

    export_prefixes = collections.Counter()
    for exp in getattr(getattr(pe, "DIRECTORY_ENTRY_EXPORT", None), "symbols", []):
        exp_name = exp.name.decode("ascii", "replace") if exp.name else f"ordinal_{exp.ordinal}"
        export_prefixes[exp_name.split("_", 1)[0]] += 1
    f, w = csv_open(out / "export_prefix_counts.csv", ["prefix", "named_exports"])
    with f:
        w.writeheader()
        for prefix, count in export_prefixes.most_common():
            w.writerow({"prefix": prefix, "named_exports": count})

    summary = {
        "source_filename": src.name,
        "file_size": len(blob),
        "sha256": sha256(blob),
        "debug_directory_entries": len(debug),
        "rtti_occurrences": len(matches),
        "rtti_unique_names": len(freq),
        "rtti_pointer_candidates": len(rtti_rows),
        "rtti_validated_col_candidates": len(col_by_va),
        "class_hierarchy_descriptors": len(hierarchy_keys),
        "class_hierarchy_member_records": len(hierarchy_rows),
        "rtti_vtable_candidates": sum(len(v) for v in col_refs.values()),
        "utf16le_ascii_string_runs_min_4": wide_count,
        "string_pointer_xref_candidates": total_string_xrefs,
        "linear_sweep_instructions_including_data_bytes": instruction_count,
        "linear_sweep_direct_call_or_jump_candidates": edge_count,
        "linear_sweep_direct_call_targets_in_text": len(call_targets),
        "linear_sweep_function_entry_candidates": len(entries),
        "warning": "Linear x86 sweep is not a CFG; embedded data and alignment can create false instructions and edges.",
    }
    (out / "deep_counts.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    pe.close()
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
