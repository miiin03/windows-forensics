"""Decode SQLite table-leaf cells and record payloads into typed values.

Pure functions, no I/O — shared by the live reader and the byte-level carver.
A *record* payload is ``header_len varint | serial-type varints... | body``.
A table-leaf *cell* is ``payload_len varint | rowid varint | record [| overflow]``.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from engine.varint import read_varint, try_read_varint, serial_type_size


@dataclass(frozen=True)
class Record:
    header_len: int
    serial_types: list[int]
    values: list


@dataclass(frozen=True)
class RecordView:
    header_len: int
    serial_types: list[int]
    values: list
    body_end: int      # offset just past the last decoded body byte
    truncated: bool


@dataclass(frozen=True)
class Cell:
    payload_len: int
    rowid: int
    header_len: int
    serial_types: list[int]
    values: list
    has_overflow: bool
    first_overflow_page: int | None
    local_payload_len: int


def decode_value(serial: int, raw: bytes, encoding: str = "utf-8"):
    """Decode one column value given its serial type and on-disk bytes."""
    if serial == 0:
        return None
    if 1 <= serial <= 6:
        return int.from_bytes(raw, "big", signed=True)
    if serial == 7:
        return struct.unpack(">d", raw)[0]
    if serial == 8:
        return 0
    if serial == 9:
        return 1
    if serial in (10, 11):
        return raw  # reserved: surface the raw bytes rather than guessing
    if serial % 2 == 0:  # >= 12 even -> BLOB
        return raw
    return raw.decode(encoding, errors="replace")  # >= 13 odd -> TEXT


def decode_record(payload: bytes, encoding: str = "utf-8") -> Record:
    """Decode a complete record payload (header + body)."""
    header_len, off = read_varint(payload, 0)
    serial_types: list[int] = []
    while off < header_len:
        serial, off = read_varint(payload, off)
        serial_types.append(serial)

    values = []
    body_off = header_len
    for serial in serial_types:
        size = serial_type_size(serial)
        raw = payload[body_off : body_off + size]
        values.append(decode_value(serial, raw, encoding))
        body_off += size

    return Record(header_len=header_len, serial_types=serial_types, values=values)


_MAX_HEADER_LEN = 4096  # an Activity record header is ~34 bytes; cap sanity


def try_decode_record(
    buf: bytes, off: int, end: int, encoding: str = "utf-8"
) -> RecordView | None:
    """Bounds-checked record decode for carving. Never raises.

    Returns a :class:`RecordView` (with ``truncated=True`` if the body runs past
    ``end``) or ``None`` if the *header* itself is unreadable/implausible. The
    column-count / fingerprint gate is the caller's job (engine.validate).
    """
    end = min(end, len(buf))
    hv = try_read_varint(buf, off, end)
    if hv is None:
        return None
    header_len, pos = hv
    header_end = off + header_len
    if header_len < 2 or header_len > _MAX_HEADER_LEN or header_end > end:
        return None

    serial_types: list[int] = []
    while pos < header_end:
        sv = try_read_varint(buf, pos, header_end)
        if sv is None:
            return None
        serial, pos = sv
        serial_types.append(serial)

    values = []
    truncated = False
    body_off = header_end
    for serial in serial_types:
        size = serial_type_size(serial)
        raw = buf[body_off : body_off + size]
        if len(raw) < size:
            truncated = True
            values.append(None)  # body ran out; column unrecoverable
        else:
            values.append(decode_value(serial, raw, encoding))
        body_off += size

    return RecordView(
        header_len=header_len,
        serial_types=serial_types,
        values=values,
        body_end=min(body_off, end),
        truncated=truncated,
    )


def local_payload_size(payload_len: int, usable: int) -> tuple[int, bool]:
    """Bytes of a table-leaf payload stored locally + whether it overflows.

    SQLite's overflow threshold math (fileformat2.html §1.6).
    """
    max_local = usable - 35
    if payload_len <= max_local:
        return payload_len, False
    min_local = ((usable - 12) * 32 // 255) - 23
    k = min_local + (payload_len - min_local) % (usable - 4)
    local = k if k <= max_local else min_local
    return local, True


def decode_table_leaf_cell(
    page: bytes,
    cell_off: int,
    usable_size: int,
    encoding: str = "utf-8",
    overflow_reader=None,
) -> Cell:
    """Decode a table-leaf cell starting at ``cell_off`` within ``page``.

    ``overflow_reader``, if given, is called ``reader(first_page, need_bytes)``
    to reassemble spilled payload; without it an overflowing cell decodes only
    its local prefix (callers should treat such records as truncated).
    """
    payload_len, off = read_varint(page, cell_off)
    rowid, off = read_varint(page, off)

    local_len, has_overflow = local_payload_size(payload_len, usable_size)
    local_payload = page[off : off + local_len]

    first_overflow_page = None
    payload = local_payload
    if has_overflow:
        first_overflow_page = struct.unpack(
            ">I", page[off + local_len : off + local_len + 4]
        )[0]
        if overflow_reader is not None:
            spilled = overflow_reader(first_overflow_page, payload_len - local_len)
            payload = local_payload + spilled

    rec = decode_record(payload, encoding)
    return Cell(
        payload_len=payload_len,
        rowid=rowid,
        header_len=rec.header_len,
        serial_types=rec.serial_types,
        values=rec.values,
        has_overflow=has_overflow,
        first_overflow_page=first_overflow_page,
        local_payload_len=local_len,
    )
