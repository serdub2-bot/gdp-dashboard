#!/usr/bin/env python3
"""Read-only structural inventory for the supplied FM2008 8.0.2 database files.

Uses only Python's standard library. Reads the ZIP files in the repository and
writes reports under inventory/database; never extracts or edits source files.
"""
from __future__ import annotations

import argparse
import collections
import csv
import gzip
import hashlib
import json
import math
import struct
import statistics
import zipfile
import zlib
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVES = [
    ROOT / "1.zip",
    ROOT / "inbox/1.zip",
    ROOT / "inbox/2.zip",
    ROOT / "inbox/3.zip",
    ROOT / "inbox/4.zip",
]
CORE_FILES = {
    "client_db.dat", "server_db.dat", "lang_db.dat",
    "pl_hist_dt.dat", "pl_hist_id.dat", "pl_hist_index.dat",
    "non_pl_hist_dt.dat", "non_pl_hist_id.dat", "non_pl_hist_index.dat",
    "802.xml",
}
HISTORY_KINDS = ("pl", "non_pl")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts = collections.Counter(data)
    n = len(data)
    return -sum((count / n) * math.log2(count / n) for count in counts.values())


def read_zlib_stream(data: bytes, offset: int) -> tuple[bytes, int]:
    obj = zlib.decompressobj()
    out = obj.decompress(data[offset:])
    out += obj.flush()
    if not obj.eof:
        raise ValueError("zlib stream did not reach EOF")
    consumed = len(data[offset:]) - len(obj.unused_data)
    return out, consumed


def scan_zlib_streams(data: bytes, min_output: int = 100_000) -> list[dict]:
    """Find complete embedded zlib streams, advancing past each accepted stream."""
    found: list[dict] = []
    pos = 9
    while pos + 2 <= len(data):
        start = data.find(b"\x78", pos)
        if start < 0 or start + 2 > len(data):
            break
        pos = start + 1
        cmf, flg = data[start], data[start + 1]
        if (cmf & 0x0f) != 8 or ((cmf << 8) | flg) % 31:
            continue
        try:
            out, consumed = read_zlib_stream(data, start)
        except zlib.error:
            continue
        except ValueError:
            continue
        if len(out) < min_output:
            continue
        found.append({"offset": start, "compressed_size": consumed,
                      "uncompressed": out, "uncompressed_size": len(out)})
        pos = start + consumed
    return found


def csv_writer(path: Path, columns: list[str]):
    fh = path.open("w", newline="", encoding="utf-8")
    writer = csv.DictWriter(fh, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    return fh, writer


def utf16_runs(data: bytes, limit: int = 4096, minimum: int = 3) -> list[str]:
    """Short aligned UTF-16LE text samples, not a full schema parser."""
    data = data[:limit - (limit % 2)]
    samples: list[str] = []
    run: list[str] = []
    for (code,) in struct.iter_unpack("<H", data):
        ch = chr(code)
        if ch.isprintable() and ch not in "\r\n\t\x0b\x0c":
            run.append(ch)
        else:
            if len(run) >= minimum:
                samples.append("".join(run))
            run = []
    if len(run) >= minimum:
        samples.append("".join(run))
    return samples[:8]


def language_id_directory(data: bytes, streams: list[dict]) -> dict[int, int | None]:
    """Match observed relative offsets to the apparent offset/ID pairs in lang_db."""
    matches: dict[int, int | None] = {}
    first_stream = min((s["offset"] for s in streams), default=len(data))
    # In the supplied 8.0.2 file the directory begins at file offset 14; each
    # full entry is (u32 offset relative to the 9-byte common header, u32 label).
    for i, stream in enumerate(streams):
        relative = stream["offset"] - 9
        locale_id = None
        search_end = min(first_stream, len(data))
        for p in range(14, search_end - 3, 4):
            if struct.unpack_from("<I", data, p)[0] == relative:
                if p + 8 <= search_end:
                    locale_id = struct.unpack_from("<I", data, p + 4)[0]
                break
        matches[i] = locale_id
    return matches


def language_string_candidates(data: bytes):
    """Conservative heuristic for [u32 id][u32 UTF-16 char count][text]."""
    seen: set[tuple[int, str, int]] = set()
    for text_offset in range(8, len(data) - 4, 2):
        string_id, char_count = struct.unpack_from("<II", data, text_offset - 8)
        if not 2 <= char_count <= 200:
            continue
        text_end = text_offset + char_count * 2
        if text_end > len(data):
            continue
        try:
            text = data[text_offset:text_end].decode("utf-16-le")
        except UnicodeDecodeError:
            continue
        if not text or not any(ch.isalpha() for ch in text):
            continue
        if any(ord(ch) < 32 for ch in text):
            continue
        row = (string_id, text, text_offset)
        if row in seen:
            continue
        seen.add(row)
        yield string_id, char_count, text, text_offset, data[text_end:text_end + 2] == b"\x00\x00"


def history_stats(files: dict[str, bytes], out: Path) -> tuple[dict, list[dict]]:
    summary: dict[str, dict] = {}
    examples: list[dict] = []
    for kind in HISTORY_KINDS:
        dt_name = f"{kind}_hist_dt.dat"
        id_name = f"{kind}_hist_id.dat"
        index_name = f"{kind}_hist_index.dat"
        if not all(name in files for name in (dt_name, id_name, index_name)):
            continue
        dt_raw, id_raw, index_raw = (files[dt_name], files[id_name], files[index_name])
        dt_body, id_body, index_body = dt_raw[9:], id_raw[9:], index_raw[9:]
        if len(id_body) % 8:
            raise ValueError(f"{id_name}: offset table is not pairs of u32")
        ranges = list(struct.iter_unpack("<II", id_body))
        if len(index_body) < 4 or (len(index_body) - 4) % 8:
            raise ValueError(f"{index_name}: index is not a u32 count followed by pairs")
        declared_count, = struct.unpack_from("<I", index_body)
        entries = list(struct.iter_unpack("<II", index_body[4:]))
        keys = [a for a, _ in entries]
        ordinals = [b for _, b in entries]
        lengths = [end - start for start, end in ranges]
        in_bounds = all(0 <= start <= end <= len(dt_body) for start, end in ranges)
        gaps = [ranges[i + 1][0] - ranges[i][1] for i in range(len(ranges) - 1)]
        sorted_keys = all(a <= b for a, b in zip(keys, keys[1:]))
        ordinal_permutation = len(ordinals) == len(ranges) and set(ordinals) == set(range(len(ranges)))
        summary[kind] = {
            "files": {"dt": dt_name, "id": id_name, "index": index_name},
            "history_entry_count_from_index_header": declared_count,
            "index_pair_count": len(entries),
            "offset_pair_count": len(ranges),
            "dt_body_bytes_after_9_byte_header": len(dt_body),
            "index_header_count_matches_pairs": declared_count == len(entries),
            "id_pair_count_matches_index_count": len(ranges) == declared_count,
            "all_id_offsets_are_ordered_and_in_bounds": in_bounds,
            "offset_range_lengths": {
                "zero_length_count": sum(length == 0 for length in lengths),
                "min": min(lengths), "median": statistics.median(lengths),
                "mean": round(statistics.mean(lengths), 3), "max": max(lengths),
                "p90": sorted(lengths)[int((len(lengths) - 1) * 0.90)],
                "p99": sorted(lengths)[int((len(lengths) - 1) * 0.99)],
            },
            "gaps_between_adjacent_offset_ranges": {
                "min": min(gaps), "median": statistics.median(gaps), "max": max(gaps),
                "constant_gap": len(set(gaps)) == 1,
            },
            "index_key_ordered_non_decreasing": sorted_keys,
            "unique_index_key_count": len(set(keys)),
            "index_ordinals_form_permutation": ordinal_permutation,
            "index_ordinals_are_identity_order": ordinals == list(range(len(ordinals))),
            "first_index_pairs": entries[:12],
            "first_offset_pairs": ranges[:12],
            "interpretation_limit": "Offset-pair/index relationship is structurally consistent; field semantics are inferred, not officially documented.",
        }
        for i in range(min(24, declared_count)):
            key, ordinal = entries[i]
            start, end = ranges[ordinal]
            examples.append({"kind": kind, "index_row": i, "index_key_u32": key,
                             "offset_pair_ordinal": ordinal, "dt_start_offset": start,
                             "dt_end_offset": end, "slice_length": end - start,
                             "offsets_in_bounds": end <= len(dt_body)})
    (out / "history_tables.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    fh, writer = csv_writer(out / "history_index_examples.csv", [
        "kind", "index_row", "index_key_u32", "offset_pair_ordinal", "dt_start_offset",
        "dt_end_offset", "slice_length", "offsets_in_bounds",
    ])
    with fh:
        writer.writerows(examples)
    return summary, examples


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", action="append", type=Path, default=None,
                        help="ZIP source; may be repeated (default: root 1.zip and inbox/1..4.zip)")
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "inventory/database")
    args = parser.parse_args()
    archives = args.archive or DEFAULT_ARCHIVES
    archives = [p if p.is_absolute() else ROOT / p for p in archives]
    out = args.out if args.out.is_absolute() else ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)

    archive_rows: list[dict] = []
    sources: dict[str, list[tuple[str, bytes]]] = collections.defaultdict(list)
    archive_meta: list[dict] = []
    for archive in archives:
        if not archive.exists():
            raise SystemExit(f"archive not found: {archive}")
        archive_blob = archive.read_bytes()
        archive_rel = str(archive.relative_to(ROOT)) if archive.is_relative_to(ROOT) else str(archive)
        archive_meta.append({"archive": archive_rel, "archive_size": len(archive_blob),
                             "archive_sha256": sha256(archive_blob)})
        with zipfile.ZipFile(archive) as zf:
            for member in zf.infolist():
                if member.is_dir():
                    continue
                data = zf.read(member)
                archive_rows.append({
                    "archive": archive_rel, "member": member.filename,
                    "member_size": member.file_size, "zip_compressed_size": member.compress_size,
                    "zip_crc32": f"{member.CRC:08x}", "zip_timestamp": "-".join(map(str, member.date_time)),
                    "zip_method": "stored" if member.compress_type == zipfile.ZIP_STORED else "deflate" if member.compress_type == zipfile.ZIP_DEFLATED else str(member.compress_type),
                    "member_sha256": sha256(data),
                })
                sources[Path(member.filename).name].append((archive_rel, data))

    with (out / "archive_members.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(archive_rows[0]), lineterminator="\n")
        writer.writeheader(); writer.writerows(archive_rows)
    (out / "archive_hashes.json").write_text(json.dumps(archive_meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    files: dict[str, bytes] = {}
    file_rows: list[dict] = []
    for name, copies in sorted(sources.items()):
        hashes = {sha256(data) for _, data in copies}
        if len(hashes) > 1:
            raise SystemExit(f"duplicate member name has different content: {name}")
        archive_names = ";".join(dict.fromkeys(archive for archive, _ in copies))
        data = copies[0][1]
        if name in CORE_FILES:
            files[name] = data
        prefix = data[:16]
        row = {
            "file": name, "source_archives": archive_names, "size_bytes": len(data),
            "sha256": sha256(data), "header_hex_0_16": prefix.hex(" "),
            "byte_entropy_bits": round(entropy(data), 6),
            "zero_byte_fraction": round(data.count(0) / max(len(data), 1), 6),
            "scope": "database core" if name in CORE_FILES and name.endswith(".dat") else "database metadata" if name in CORE_FILES else "auxiliary, not parsed as a database table",
        }
        if data.startswith(b"\x02\x01"):
            row["signature"] = data[:2].hex()
            row["table_tag"] = data[2:6].decode("ascii", "replace") if len(data) >= 6 else ""
            row["format_version_bytes"] = data[6:9].hex() if len(data) >= 9 else ""
        if name in ("client_db.dat", "server_db.dat"):
            unpacked, consumed = read_zlib_stream(data, 9)
            row.update({"uncompressed_bytes": len(unpacked), "zlib_offset": 9,
                        "zlib_compressed_bytes": consumed, "zlib_eof": True,
                        "zlib_unused_tail_bytes": len(data) - 9 - consumed,
                        "compression_ratio_raw_over_expanded": round(len(data) / len(unpacked), 6),
                        "expanded_entropy_bits": round(entropy(unpacked), 6),
                        "expanded_zero_fraction": round(unpacked.count(0) / len(unpacked), 6)})
        elif name == "lang_db.dat":
            row["lang_stream_scan"] = "separate embedded zlib streams; detailed table in lang_streams.csv"
        elif name.endswith("_hist_dt.dat"):
            row["raw_data_bytes_after_common_header"] = len(data) - 9
        elif name.endswith("_hist_id.dat"):
            row["u32_count_after_common_header"] = (len(data) - 9) // 4
        elif name.endswith("_hist_index.dat"):
            if len(data) >= 13:
                row["declared_pair_count"] = struct.unpack_from("<I", data, 9)[0]
                row["observed_pair_count"] = (len(data) - 13) // 8
        elif name == "802.xml":
            root = ElementTree.fromstring(data)
            props = {el.attrib.get("id"): el.attrib.get("value") for el in root.findall(".//string")}
            row.update({"xml_version": root.attrib.get("version"), "database_name": props.get("name"),
                        "database_author": props.get("author"), "database_description": props.get("description"),
                        "database_version": props.get("version"), "required_game_version": props.get("required_version")})
        elif name == "1.fm":
            try:
                unpacked, consumed = read_zlib_stream(data, 14)
                row.update({"embedded_zlib_offset": 14, "embedded_zlib_compressed_bytes": consumed,
                            "embedded_zlib_output_bytes": len(unpacked),
                            "trailing_opaque_bytes": len(data) - 14 - consumed,
                            "classification_note": "fmf. container-like file; not a standard tad. database table; large trailing payload not decoded"})
            except (zlib.error, ValueError):
                row["classification_note"] = "not a standard tad. database table"
        file_rows.append(row)

    with (out / "database_files.csv").open("w", newline="", encoding="utf-8") as fh:
        columns = list(dict.fromkeys(k for row in file_rows for k in row))
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        writer.writeheader(); writer.writerows(file_rows)

    if "lang_db.dat" not in files:
        raise SystemExit("lang_db.dat missing from supplied archives")
    lang_blob = files["lang_db.dat"]
    streams = scan_zlib_streams(lang_blob)
    locale_ids = language_id_directory(lang_blob, streams)
    if len(streams) != 20:
        print(f"WARNING: expected around 20 large lang streams, found {len(streams)}")
    lang_rows = []
    for i, stream in enumerate(streams):
        expanded = stream["uncompressed"]
        text = expanded.decode("utf-16-le", errors="ignore")
        cyrillic = sum(("А" <= ch <= "я") or ch in "Ёё" for ch in text)
        lang_rows.append({
            "stream_index_by_file_offset": i, "file_offset": f"0x{stream['offset']:08x}",
            "offset_relative_to_9_byte_header": f"0x{stream['offset'] - 9:08x}",
            "language_id_candidate": "" if locale_ids.get(i) is None else locale_ids[i],
            "compressed_bytes": stream["compressed_size"], "expanded_bytes": len(expanded),
            "leading_u32_candidate_count": struct.unpack_from("<I", expanded)[0] if len(expanded) >= 4 else "",
            "cyrillic_codepoints": cyrillic,
            "expanded_sha256": sha256(expanded),
            "first_aligned_utf16_samples": " | ".join(utf16_runs(expanded, 2048, 3)),
            "zlib_verified": True,
        })
    digest_counts = collections.Counter(row["expanded_sha256"] for row in lang_rows)
    digest_sizes = {row["expanded_sha256"]: row["expanded_bytes"] for row in lang_rows}
    for row in lang_rows:
        row["same_expanded_payload_count"] = digest_counts[row["expanded_sha256"]]
    with (out / "lang_streams.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(lang_rows[0]), lineterminator="\n")
        writer.writeheader(); writer.writerows(lang_rows)

    russian = max(streams, key=lambda s: sum(
        ("А" <= ch <= "я") or ch in "Ёё"
        for ch in s["uncompressed"].decode("utf-16-le", errors="ignore")
    ))
    string_count = 0
    with gzip.open(out / "russian_string_candidates.tsv.gz", "wt", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, delimiter="\t", lineterminator="\n")
        writer.writerow(["string_id_candidate", "char_count_candidate", "text", "chunk_offset", "nul_terminated"])
        for string_id, char_count, text, text_offset, terminated in language_string_candidates(russian["uncompressed"]):
            writer.writerow([string_id, char_count, text, text_offset, str(terminated).lower()])
            string_count += 1

    history, _ = history_stats(files, out)
    metrics = {
        "source_archives": archive_meta,
        "database_files_seen": len(files),
        "lang_db": {
            "raw_bytes": len(lang_blob), "zlib_stream_count": len(streams),
            "expanded_bytes_sum": sum(s["uncompressed_size"] for s in streams),
            "unique_expanded_payload_count": len(digest_counts),
            "unique_expanded_bytes_sum": sum(digest_sizes.values()),
            "stream_directory_language_id_candidates": sum(v is not None for v in locale_ids.values()),
            "russian_stream_file_offset": f"0x{russian['offset']:08x}",
            "russian_stream_expanded_bytes": russian["uncompressed_size"],
            "russian_stream_cyrillic_codepoints": max(r["cyrillic_codepoints"] for r in lang_rows),
            "heuristic_string_candidates_written": string_count,
            "string_extraction_warning": "Candidate dump uses an aligned u32-id/u32-length/UTF-16 pattern; it is a search aid, not a complete authoritative schema decode.",
        },
        "history_tables": history,
        "scope_note": "No league, match, roster, or patch experiment analysis is included.",
    }
    (out / "database_summary.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_russian_readme(out, file_rows, metrics)
    print(json.dumps({
        "output": str(out), "database_file_count": len(files),
        "language_stream_count": len(streams), "language_expanded_total": metrics["lang_db"]["expanded_bytes_sum"],
        "russian_string_candidates": string_count,
        "history_counts": {k: v["history_entry_count_from_index_header"] for k, v in history.items()},
    }, indent=2, ensure_ascii=False))


def write_russian_readme(out: Path, rows: list[dict], metrics: dict) -> None:
    by_name = {row["file"]: row for row in rows}
    lang = metrics["lang_db"]
    lines = [
        "# База Football Manager 2008 8.0.2 — структурный разбор файлов",
        "",
        "## Объём и методика",
        "",
        "Проведён read-only разбор файлов базы из исходных ZIP-архивов. Для отдельных проверок использовались временные копии в `/tmp/fm_db_analysis`; исходные ZIP, базы и сохранения не изменялись. Скрипт воспроизведения читает ZIP members в памяти и записывает только отчёты. Материалы `fm2008/dbpatch/` не изменялись. Этот документ намеренно не рассматривает прежние игровые, лиговые, ростерные или патч-эксперименты.",
        "",
        "Исходные архивы не дублируются в этой папке. Их SHA-256, состав, размеры участников, ZIP CRC и временные метки доступны в `archive_hashes.json` и `archive_members.csv`; SHA-256 каждого файла и метаданные таблиц — в `database_files.csv`.",
        "",
        "## Состав присланного набора",
        "",
        "| Файл | Наблюдаемая структура |",
        "|---|---|",
        "| `client_db.dat` | таблица `tad.`; один цельный zlib-поток после 9-байтового заголовка |",
        "| `server_db.dat` | таблица `tad.`; один цельный zlib-поток после 9-байтового заголовка |",
        "| `lang_db.dat` | `tad.`-контейнер с 20 цельными встроенными zlib-потоками и наблюдаемой таблицей смещений/числовых меток |",
        "| `pl_hist_dt/id/index.dat` | сырая область данных, пары u32-смещений и индекс count + пары `(key, ordinal)` |",
        "| `non_pl_hist_dt/id/index.dat` | аналогичная трёхфайловая схема; другой размер и перестановка ordinal |",
        "| `802.xml` | метаданные обновления базы |",
        "| `1.fm` из `inbox/1.zip` | отдельный файл с сигнатурой `fmf.`, не стандартная таблица `tad.`; хвостовой payload не декодировался |",
        "",
        "Корневой `1.zip` и `inbox/1.zip` — разные архивы. Первый содержит non-player history и `802.xml`, второй — `1.fm`; не следует путать их по имени.",
        "",
        "Временные метки внутри ZIP неоднородны: большинство файлов базы имеют метку `2008-03-08`, `client_db.dat` — `2026-10-25`, `1.fm` — `2026-10-29`. Это только записанные в ZIP метаданные: они не устанавливают, когда были созданы/изменены байты, и не доказывают совпадение набора с официальной поставкой. Для проверки идентичности сохранены хэши.",
        "",
        "### Размеры файлов",
        "",
        "| Файл | На диске, байт | Распакованный объём / структура | SHA-256, первые 16 hex |",
        "|---|---:|---:|---|",
    ]
    for name in ("client_db.dat", "server_db.dat", "lang_db.dat", "pl_hist_dt.dat", "pl_hist_id.dat", "pl_hist_index.dat", "non_pl_hist_dt.dat", "non_pl_hist_id.dat", "non_pl_hist_index.dat", "802.xml", "1.fm"):
        row = by_name.get(name)
        if not row:
            continue
        expanded = row.get("uncompressed_bytes") or row.get("raw_data_bytes_after_common_header") or row.get("embedded_zlib_output_bytes") or "—"
        if isinstance(expanded, int):
            expanded = f"{expanded:,}"
        if name == "lang_db.dat":
            expanded = f"{lang['expanded_bytes_sum']:,} байт в zlib-потоках"
        if name.endswith("_hist_id.dat"):
            count = int(row.get("u32_count_after_common_header", 0))
            expanded = f"{count:,} u32 = {count // 2:,} пар смещений"
        if name.endswith("_hist_index.dat"):
            expanded = f"{int(row.get('observed_pair_count', 0)):,} пар key/ordinal"
        if name == "1.fm":
            expanded = f"встроенный поток {row.get('embedded_zlib_output_bytes', 0):,} байт; хвост {row.get('trailing_opaque_bytes', 0):,} байт не декодирован"
        lines.append(f"| `{name}` | {row['size_bytes']:,} | {expanded} | `{row['sha256'][:16]}…` |")
    lines += [
        "",
        "### Общий формат контейнеров",
        "",
        "Все девять файлов `.dat` начинаются с `02 01` и ASCII-тега `tad.`. Наблюдаемый общий заголовок — 9 байт: сигнатура, четырёхбайтовый тег таблицы и три байта версии/формата. `client_db.dat`, `server_db.dat`, `lang_db.dat` и history-index используют `77 04 00`; history data/offset используют `01 00 00`.",
        "",
        "`client_db.dat` и `server_db.dat` содержат ровно по одному zlib-потоку с позиции `0x9`. Оба потока дошли до конца, контрольные суммы прошли проверку zlib, остаточных байтов после потоков нет. Распакованные размеры: 16,011,772 и 33,765,851 байт. Их низкая энтропия после распаковки и высокая доля нулевых байтов согласуются со структурированным бинарным содержимым, но сами по себе не раскрывают типы полей.",
        "",
        f"В `lang_db.dat` найдено {lang['zlib_stream_count']} полных крупных zlib-потоков общим размером {lang['expanded_bytes_sum']:,} байт. Это {lang['unique_expanded_payload_count']} различных распакованных блоков ({lang['unique_expanded_bytes_sum']:,} байт при учёте точных дублей один раз). Для каждого потока проверены границы, длина и контрольная сумма zlib.",
        "",
        "## Таблица локализаций",
        "",
        "`lang_streams.csv` содержит файловые смещения, размеры, SHA-256 распакованного содержимого, кандидатные числовые ID языка, количество кириллических символов, первые примеры UTF-16LE и число потоков с идентичным содержимым. Наблюдаемые u32-смещения из каталога совпадают со стартами zlib-потоков, если считать их относительно общего 9-байтового заголовка. Один последний поток имеет смещение, но соседняя метка до начала сжатых байтов полностью не читается; ID намеренно оставлен пустым.",
        "",
        f"Поток с наибольшим количеством кириллицы начинается по файловому смещению `0x00dd936e`, распаковывается в {lang['russian_stream_expanded_bytes']:,} байт и содержит {lang['russian_stream_cyrillic_codepoints']:,} кириллических символов. Кандидатная числовая метка — `17`; соответствие русскому языку определяется по содержимому, а не по внешней таблице кодов локалей.",
        "",
        f"`russian_string_candidates.tsv.gz` содержит {lang['heuristic_string_candidates_written']:,} кандидатных строк UTF-16LE из этого потока. Эвристика ищет выровненную последовательность `[u32 id][u32 длина в символах][UTF-16LE текст]`, затем отбрасывает строки с управляющими символами. Это вспомогательный индекс для поиска, а не доказанный полный разбор грамматики; список не гарантированно полный или уникальный.",
        "",
        "## History-файлы: проверяемая связь таблиц",
        "",
        "Для обеих history-групп подтверждена одинаковая размерность:",
        "",
        "1. `*_hist_index.dat`: после 9-байтового заголовка — u32-счётчик, затем ровно N пар `(u32 key, u32 ordinal)`.",
        "2. `*_hist_id.dat`: после заголовка — ровно N пар `(u32 start, u32 end)`.",
        "3. `*_hist_dt.dat`: сырая область, в диапазоне которой лежат все пары смещений. Смещения интерпретируются относительно тела после общего заголовка; это наиболее согласованная с размерами трактовка.",
        "",
        "| Набор | N | Пустые диапазоны | Длина диапазона: медиана / p90 / максимум | Промежуток между диапазонами | Свойства индекса |",
        "|---|---:|---:|---|---:|---|",
    ]
    for kind in HISTORY_KINDS:
        h = metrics["history_tables"].get(kind)
        if not h:
            continue
        lens = h["offset_range_lengths"]
        gaps = h["gaps_between_adjacent_offset_ranges"]
        ord_text = "исходный порядок 0..N−1" if h["index_ordinals_are_identity_order"] else "перестановка 0..N−1"
        lines.append(f"| `{kind}` | {h['history_entry_count_from_index_header']:,} | {lens['zero_length_count']:,} | {lens['median']} / {lens['p90']} / {lens['max']} байт | {gaps['min']} байт (постоянный: {gaps['constant_gap']}) | ключи не убывают, {h['unique_index_key_count']:,} уникальных; ordinal — {ord_text} |")
    lines += [
        "",
        "Все пары удовлетворяют `start <= end <= размер тела dt`. У player-history ordinal-ы идут в исходном порядке; у non-player-history образуют полную перестановку. Расстояние от конца одного диапазона до старта следующего постоянно: 22 байта у player и 18 у non-player. Наличие таких промежутков установлено арифметически; их назначение не определено. Это подтверждает структурную связь «индекс → пары смещений → область данных», но не расшифровывает отдельные события или поля.",
        "",
        "Подробные проверки — в `history_tables.json`; первые сопоставления индексов и диапазонов — в `history_index_examples.csv`.",
        "",
        "## Что пока не установлено",
        "",
        "- Полная грамматика записей `client_db.dat`, `server_db.dat`, локализаций и history `*_dt.dat` в этом разборе не восстановлена; гипотетические типы полей не подписывались.",
        "- `1.fm` учтён только как вспомогательный файл: его короткий встроенный zlib-поток распаковывается в структуру с тегом `tad.`, но остальная большая область непрозрачна. Файл не классифицирован как стандартная таблица базы и не копировался в отчёт.",
        "- Не запускалась игра, не менялись база/EXE/сохранения и не выполнялись поведенческие эксперименты.",
        "",
        "## Воспроизведение",
        "",
        "Из корня репозитория, Python standard library:",
        "",
        "```sh",
        "python3 'fm 08 for devin/database_analysis.py' \\",
        "  --out 'fm 08 for devin/inventory/database'",
        "```",
        "",
        "По умолчанию скрипт читает корневой `1.zip` и `inbox/1.zip`–`inbox/4.zip`; исходные файлы из ZIP не извлекаются и не изменяются.",
        "",
    ]
    (out / "README.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
