#!/usr/bin/env python3
"""Контейнер файлов базы Football Manager 2008 (`*.dat`).

Формат, проверенный на реальных файлах 8.0.2:

    смещение 0   2 байта   всегда 02 01
    смещение 2   4 байта   ASCII-метка таблицы, обычно b"tad."
    смещение 6   3 байта   версия/флаги формата: 77 04 00 (сжатые), 01 00 00 (история)
    смещение 9   ...       либо один zlib-поток (78 9c), либо набор записей

`client_db.dat` и `server_db.dat` — ровно один zlib-поток от смещения 9 до конца
файла. `lang_db.dat` — отдельные zlib-потоки (по одному на язык), между ними
таблицы смещений. Поэтому здесь два инструмента: `Container` (один поток) и
`zlib_streams()` (файл из нескольких потоков).

Ключевой принцип: любая правка делается на распакованных данных, затем файл
пишется заново, и результат **проверяется обратным чтением**. Если проверка не
прошла — файл не записывается.
"""
from __future__ import annotations

import zlib
from dataclasses import dataclass
from pathlib import Path

MAGIC = b"\x02\x01tad."
HEADER_LEN = 9
ZLIB_MARK = b"\x78\x9c"


def is_zlib_header(pair: bytes) -> bool:
    """Проверка заголовка zlib: CM=8 (deflate) и (CMF*256+FLG) % 31 == 0.

    Уровни сжатия дают разные вторые байты: 78 01, 78 9c, 78 da — все валидны.
    """
    if len(pair) < 2:
        return False
    cmf, flg = pair[0], pair[1]
    return (cmf & 0x0F) == 8 and ((cmf << 8) | flg) % 31 == 0


class DbError(RuntimeError):
    """Ошибка формата или проверки целостности."""


@dataclass
class Container:
    """Один .dat-файл с единственным zlib-потоком внутри."""

    path: Path
    header: bytes
    body: bytes
    compressed: bool

    # ------------------------------------------------------------------ чтение
    @classmethod
    def load(cls, path: str | Path) -> "Container":
        path = Path(path)
        blob = path.read_bytes()
        if len(blob) < HEADER_LEN:
            raise DbError(f"{path.name}: файл короче заголовка")
        if blob[:2] != b"\x02\x01":
            raise DbError(f"{path.name}: неизвестный сигнатурный байт {blob[:2]!r}")
        header, body = blob[:HEADER_LEN], blob[HEADER_LEN:]
        if is_zlib_header(body[:2]):
            return cls(path, header, body, True)
        return cls(path, header, body, False)

    @property
    def version(self) -> bytes:
        return self.header[6:9]

    @property
    def tag(self) -> bytes:
        return self.header[2:6]

    # ------------------------------------------------------------- данные
    def decompressed(self) -> bytes:
        """Распакованное содержимое. Для несжатых таблиц — тело как есть."""
        if not self.compressed:
            return self.body
        try:
            obj = zlib.decompressobj()
            data = obj.decompress(self.body)
            data += obj.flush()
        except zlib.error as exc:
            raise DbError(f"{self.path.name}: zlib не читается ({exc})") from exc
        return data

    # ------------------------------------------------------------- запись
    def save(self, out: str | Path, data: bytes, level: int = 9, verify: bool = True) -> Path:
        """Записать новый файл с подменённым содержимым.

        Заголовок (включая версию формата) сохраняется как в оригинале, чтобы
        игра приняла файл как тот же тип таблицы.
        """
        out = Path(out)
        payload = zlib.compress(data, level) if self.compressed else data
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(self.header + payload)

        if verify:
            back = Container.load(out).decompressed()
            if back != data:
                raise DbError(f"{out.name}: проверка после записи не прошла — файл удалён")
        return out

    def pack(self, data: bytes, level: int = 9) -> bytes:
        """Собрать файл в памяти: заголовок + сжатое содержимое."""
        payload = zlib.compress(data, level) if self.compressed else bytes(data)
        return self.header + payload

    # ------------------------------------------------------------- отчёты
    def describe(self) -> dict:
        data = self.decompressed()
        return {
            "file": self.path.name,
            "tag": self.tag.decode("ascii", "replace"),
            "version": self.version.hex(),
            "compressed": self.compressed,
            "on_disk": self.path.stat().st_size,
            "uncompressed": len(data),
            "ratio": round(len(data) / max(self.path.stat().st_size, 1), 2),
        }


def zlib_streams(blob: bytes, min_size: int = 50_000) -> list[tuple[int, bytes]]:
    """Все самостоятельные zlib-потоки в файле: [(смещение, распакованные данные)].

    Так устроен `lang_db.dat`: каждый язык — отдельный поток. Дубликаты
    отбрасываются по первым 2 КБ содержимого.
    """
    found: list[tuple[int, bytes]] = []
    seen: set[bytes] = set()
    pos = 0
    while True:
        idx = blob.find(b"\x78", pos)
        if idx < 0:
            break
        pos = idx + 1
        if not is_zlib_header(blob[idx:idx + 2]):
            continue
        try:
            obj = zlib.decompressobj()
            data = obj.decompress(blob[idx:]) + obj.flush()
        except zlib.error:
            continue
        if len(data) < min_size:
            continue
        key = data[:2048]
        if key in seen:
            continue
        seen.add(key)
        found.append((idx, data))
    return found


def is_russian(data: bytes, threshold: int = 500) -> bool:
    """Грубая проверка: есть ли в блоке заметное количество кириллицы."""
    text = data.decode("utf-16-le", errors="ignore")
    return sum(1 for ch in text if "А" <= ch <= "я" or ch in "Ёё") >= threshold


def pick_russian(streams: list[tuple[int, bytes]]) -> tuple[int, bytes]:
    """Поток с наибольшим количеством кириллицы — русская локализация."""
    best = max(streams, key=lambda t: sum(
        1 for ch in t[1].decode("utf-16-le", errors="ignore") if "А" <= ch <= "я" or ch in "Ёё"
    ), default=(0, b""))
    if not best[1] or not is_russian(best[1]):
        raise DbError("русская таблица строк не найдена")
    return best


# ------------------------------------------------------------------ строки
def compress_exact(data: bytes, target_len: int) -> bytes:
    """Сжать так, чтобы длина потока была ровно `target_len` байт.

    Зачем: в `lang_db.dat` в начале файла лежит список смещений потоков. Если
    пересжать изменённый поток в другой размер, все смещения после него станут
    неверными и игра базу не примет. Поэтому хвост добивается пустыми
    stored-блоками deflate (они ничего не добавляют к данным).

    Пустой stored-блок занимает 5 байт, поэтому подходит любой запас, кратный 5.
    Перебираем уровни и стратегии сжатия и берём первый, который попадает.
    """
    import zlib as _z

    data = bytes(data)
    strategies = (_z.Z_DEFAULT_STRATEGY, _z.Z_FILTERED, _z.Z_RLE, _z.Z_FIXED)
    best: tuple[int, bytes] | None = None
    for level in (9, 8, 7, 6, 5, 4, 3, 2, 1, 0):
        for strategy in strategies:
            try:
                obj = _z.compressobj(level, _z.DEFLATED, 15, 8, strategy)
                body = obj.compress(data) + obj.flush(_z.Z_SYNC_FLUSH)
            except Exception:
                continue
            pad = target_len - (len(body) + 5 + 4)  # финальный блок + adler32
            if pad < 0 or pad % 5:
                if best is None or len(body) < best[0]:
                    best = (len(body), body)
                continue
            filler = b"\x00\x00\x00\xff\xff" * (pad // 5)
            stream = body + filler + b"\x01\x00\x00\xff\xff" + \
                _z.adler32(data).to_bytes(4, "big")
            if len(stream) == target_len and _z.decompress(stream) == data:
                return stream
    hint = f" (минимум {best[0] + 9} байт)" if best else ""
    raise DbError(f"не удалось сжать в {target_len} байт без сдвига смещений{hint}")


def utf16_offsets(haystack: bytes, needle: str) -> list[int]:
    """Все смещения строки в UTF-16LE-блоке."""
    raw = needle.encode("utf-16-le")
    out: list[int] = []
    pos = 0
    while True:
        idx = haystack.find(raw, pos)
        if idx < 0:
            return out
        out.append(idx)
        pos = idx + 2


def read_utf16_at(blob: bytes, offset: int, max_len: int = 200) -> str:
    """Прочитать строку UTF-16LE с заданного смещения (до нулевого символа)."""
    raw = bytearray()
    pos = offset
    while pos + 1 < len(blob) and len(raw) < max_len * 2:
        pair = blob[pos:pos + 2]
        pos += 2
        if pair == b"\x00\x00":
            break
        raw += pair
    return raw.decode("utf-16-le", errors="replace")
