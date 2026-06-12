"""SQLite varint + serial-type primitives.

A SQLite varint is a 1-9 byte big-endian integer. The high bit (0x80) of each
of the first 8 bytes is a continuation flag; the low 7 bits carry data. If 8
bytes all have the continuation bit set, the 9th byte contributes all 8 of its
bits (so the full 64-bit range is reachable).

This module has zero dependencies on purpose: it is the bedrock both the live
reader and the byte-level carver build on.
"""

from __future__ import annotations

# Serial-type sizes for the fixed (non length-encoded) types 0..9.
# 10/11 are reserved for internal use; we report size 0 and kind "reserved".
_FIXED_SIZE = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 6, 6: 8, 7: 8, 8: 0, 9: 0}


def read_varint(buf: bytes, off: int) -> tuple[int, int]:
    """Read a varint at ``off``. Return ``(value, new_offset)``.

    Assumes the buffer is long enough. For untrusted/truncated data use
    :func:`try_read_varint`.
    """
    result = 0
    for i in range(9):
        byte = buf[off + i]
        if i == 8:
            # 9th byte: all 8 bits contribute.
            return ((result << 8) | byte) & 0xFFFFFFFFFFFFFFFF, off + 9
        result = (result << 7) | (byte & 0x7F)
        if not (byte & 0x80):
            return result, off + i + 1
    # Unreachable: the i == 8 branch always returns.
    return result, off + 9


def try_read_varint(buf: bytes, off: int, end: int) -> tuple[int, int] | None:
    """Bounds-checked varint read confined to ``buf[off:end]``.

    Returns ``(value, new_offset)`` or ``None`` if the varint runs past ``end``
    (truncation). Never raises on truncated input — the carver relies on this.
    """
    end = min(end, len(buf))
    result = 0
    for i in range(9):
        pos = off + i
        if pos >= end:
            return None
        byte = buf[pos]
        if i == 8:
            return ((result << 8) | byte) & 0xFFFFFFFFFFFFFFFF, pos + 1
        result = (result << 7) | (byte & 0x7F)
        if not (byte & 0x80):
            return result, pos + 1
    return result, off + 9


def serial_type_size(serial: int) -> int:
    """Bytes a value of this serial type occupies on disk."""
    if serial < 12:
        return _FIXED_SIZE.get(serial, 0)
    return (serial - 12) // 2  # 12+ even -> BLOB, 13+ odd -> TEXT, same byte count


def serial_type_kind(serial: int) -> str:
    """Classify a serial type into a coarse kind."""
    if serial == 0:
        return "null"
    if 1 <= serial <= 6:
        return "int"
    if serial == 7:
        return "float"
    if serial == 8:
        return "zero"
    if serial == 9:
        return "one"
    if serial in (10, 11):
        return "reserved"
    return "blob" if serial % 2 == 0 else "text"
