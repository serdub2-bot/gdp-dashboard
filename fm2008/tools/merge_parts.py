#!/usr/bin/env python3
"""Склейка разрезанного архива из inbox/ и проверка целостности.

Нужен, потому что через веб-интерфейс GitHub в репозиторий можно загрузить
файл не больше 25 МБ, а база FM2008 в архиве крупнее. Поэтому архив режется
на части, части грузятся в inbox/, а скрипт собирает их обратно.

Поддерживаются оба способа нарезки:
  7-Zip (Windows):  db.zip.001, db.zip.002, ...      -> --kind volumes
  split (Linux/macOS): db.zip.part-aa, .part-ab, ...  -> --kind parts
  вручную:          db.zip-01, db.zip-02, ...         -> --kind numbered

Использование:
    python3 merge_parts.py                       # автоопределение
    python3 merge_parts.py --kind volumes        # 7-Zip
    python3 merge_parts.py --out /tmp/db.zip     # куда положить результат

Скрипт печатает sha256 итогового файла — сверьте его с исходным архивом
(`sha256sum db.zip` на Linux, `certutil -hashfile db.zip SHA256` на Windows).
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # корень репозитория
INBOX = ROOT / "inbox"

PATTERNS = {
    "volumes": re.compile(r"^(?P<base>.+\.zip)\.(?P<num>\d{3})$"),
    "parts": re.compile(r"^(?P<base>.+\.zip)\.part-(?P<num>[a-z]{2})$"),
    "numbered": re.compile(r"^(?P<base>.+\.zip)[-_.](?P<num>\d{1,3})$"),
}


def collect(kind: str, stem: str | None) -> tuple[str, list[Path]]:
    rx = PATTERNS[kind]
    groups: dict[str, list[tuple[str, Path]]] = {}
    for p in sorted(INBOX.iterdir()):
        if not p.is_file():
            continue
        m = rx.match(p.name)
        if not m:
            continue
        base = m.group("base")
        if stem and stem not in base:
            continue
        groups.setdefault(base, []).append((m.group("num"), p))

    if not groups:
        raise SystemExit(f"в {INBOX} не найдено частей типа «{kind}»")
    base = max(groups, key=lambda k: len(groups[k]))
    files = sorted(groups[base], key=lambda t: t[0])
    return base, [p for _, p in files]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=PATTERNS, default=None,
                    help="способ нарезки (по умолчанию определяется сам)")
    ap.add_argument("--stem", default=None, help="подстрока имени архива, если частей несколько")
    ap.add_argument("--out", default=None, help="куда записать склеенный файл")
    args = ap.parse_args()

    if not INBOX.is_dir():
        raise SystemExit(f"нет папки {INBOX}")

    kind = args.kind
    if kind is None:
        for candidate in PATTERNS:
            try:
                collect(candidate, args.stem)
                kind = candidate
                break
            except SystemExit:
                continue
        if kind is None:
            raise SystemExit("частей не найдено — проверьте имена файлов в inbox/")

    base, files = collect(kind, args.stem)
    out = Path(args.out) if args.out else Path("/tmp") / base
    print(f"способ: {kind}, файл: {base}")
    print(f"частей: {len(files)}")
    for f in files:
        print(f"  {f.name:40} {f.stat().st_size:>12,} байт")

    h = hashlib.sha256()
    total = 0
    with out.open("wb") as dst:
        for f in files:
            with f.open("rb") as src:
                while chunk := src.read(1 << 20):
                    dst.write(chunk)
                    h.update(chunk)
                    total += len(chunk)

    print(f"\nсобрано: {out} ({total:,} байт)")
    print(f"sha256: {h.hexdigest()}")

    try:
        with zipfile.ZipFile(out) as z:
            bad = z.testzip()
            names = z.namelist()
            print(f"архив читается, файлов внутри: {len(names)}, повреждённых: {bad or 'нет'}")
            for n in names[:40]:
                print(f"  {n}")
            if len(names) > 40:
                print(f"  ... и ещё {len(names) - 40}")
    except zipfile.BadZipFile as exc:
        print(f"ВНИМАНИЕ: это не ZIP или он повреждён: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
