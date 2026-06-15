"""Tests for SQLite varint + serial-type decoding (engine.varint)."""

import pytest

from engine.varint import (
    read_varint,
    try_read_varint,
    serial_type_size,
    serial_type_kind,
)


# --- read_varint: value + new offset ----------------------------------------

@pytest.mark.parametrize(
    "data, off, expected_value, expected_off",
    [
        (b"\x00", 0, 0, 1),               # single byte zero
        (b"\x7f", 0, 127, 1),             # single byte max (no continuation)
        (b"\x81\x00", 0, 128, 2),         # two-byte: (1<<7)|0
        (b"\x81\x01", 0, 129, 2),         # two-byte: (1<<7)|1
        (b"\x82\x00", 0, 256, 2),         # (2<<7)|0
        (b"\xac\x02", 0, 0x1602, 2),      # 0xac=cont(0x2c), 0x02 -> (0x2c<<7)|2
        (b"\xff\x7f", 0, 0x3FFF, 2),      # max 2-byte
    ],
)
def test_read_varint_basic(data, off, expected_value, expected_off):
    value, new_off = read_varint(data, off)
    assert value == expected_value
    assert new_off == expected_off


def test_read_varint_respects_offset():
    # varint sits after a 3-byte prefix
    buf = b"\xaa\xbb\xcc\x81\x01"
    value, new_off = read_varint(buf, 3)
    assert value == 129
    assert new_off == 5


def test_read_varint_nine_byte_max():
    # 8 continuation bytes (0xff) + final byte uses all 8 bits -> 2**64 - 1
    buf = b"\xff\xff\xff\xff\xff\xff\xff\xff\xff"
    value, new_off = read_varint(buf, 0)
    assert value == (2**64 - 1)
    assert new_off == 9


def test_read_varint_nine_byte_stops_at_nine():
    # all high bits set across 9 bytes -> exactly 9 consumed, 10th ignored
    buf = b"\x81\x81\x81\x81\x81\x81\x81\x81\x01\x99"
    value, new_off = read_varint(buf, 0)
    assert new_off == 9


# --- try_read_varint: bounds-checked variant --------------------------------

def test_try_read_varint_ok():
    assert try_read_varint(b"\x81\x01", 0, 2) == (129, 2)


def test_try_read_varint_truncated_returns_none():
    # continuation bit set but buffer ends -> None, never raises
    assert try_read_varint(b"\x81", 0, 1) is None


def test_try_read_varint_offset_past_end_returns_none():
    assert try_read_varint(b"\x01", 5, 1) is None


def test_try_read_varint_respects_end_below_buffer_len():
    # end cuts off the continuation; must not read past `end`
    assert try_read_varint(b"\x81\x01", 0, 1) is None


# --- serial_type_size --------------------------------------------------------

@pytest.mark.parametrize(
    "serial, size",
    [
        (0, 0),    # NULL
        (1, 1),
        (2, 2),
        (3, 3),
        (4, 4),
        (5, 6),
        (6, 8),
        (7, 8),    # IEEE float
        (8, 0),    # constant 0
        (9, 0),    # constant 1
        (12, 0),   # BLOB length 0
        (13, 0),   # TEXT length 0
        (44, 16),  # BLOB (44-12)/2 = 16  (the GUID fingerprint)
        (325, 156),  # TEXT (325-13)/2 = 156 (real AppId)
        (101, 44),   # TEXT (101-13)/2 = 44
        (14, 1),   # BLOB (14-12)/2 = 1
        (15, 1),   # TEXT (15-13)/2 = 1
    ],
)
def test_serial_type_size(serial, size):
    assert serial_type_size(serial) == size


# --- serial_type_kind --------------------------------------------------------

@pytest.mark.parametrize(
    "serial, kind",
    [
        (0, "null"),
        (1, "int"),
        (4, "int"),
        (5, "int"),
        (6, "int"),
        (7, "float"),
        (8, "zero"),
        (9, "one"),
        (10, "reserved"),
        (11, "reserved"),
        (12, "blob"),
        (44, "blob"),
        (13, "text"),
        (325, "text"),
    ],
)
def test_serial_type_kind(serial, kind):
    assert serial_type_kind(serial) == kind
