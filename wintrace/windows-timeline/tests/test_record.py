"""Tests for engine.record (record-header + cell decoding)."""

import struct

import pytest

from engine.record import (
    decode_record,
    decode_table_leaf_cell,
    local_payload_size,
    Record,
    Cell,
)


def enc_varint(n: int) -> bytes:
    """Encode an unsigned int as a SQLite varint (test helper)."""
    if n == 0:
        return b"\x00"
    out = []
    if n > (2**56 - 1):
        out.append(n & 0xFF)
        n >>= 8
        for _ in range(8):
            out.append((n & 0x7F) | 0x80)
            n >>= 7
        return bytes(reversed(out))
    while n:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out[0] &= 0x7F  # last byte (becomes first after reverse) has no continuation
    return bytes(reversed(out))


def make_record(serial_types_and_bodies):
    """Build a flat record payload from [(serial, body_bytes), ...]."""
    serials = b"".join(enc_varint(s) for s, _ in serial_types_and_bodies)
    header_len = len(serials) + 1  # +1 assumes header_len fits in one varint
    # header_len includes the header_len varint itself; recompute if multi-byte
    hl_bytes = enc_varint(header_len)
    if len(hl_bytes) != 1:
        header_len = len(serials) + len(hl_bytes)
        hl_bytes = enc_varint(header_len)
    header = hl_bytes + serials
    body = b"".join(b for _, b in serial_types_and_bodies)
    return header + body


# --- enc_varint self-check ---------------------------------------------------

def test_enc_varint_roundtrip():
    from engine.varint import read_varint
    for n in [0, 1, 127, 128, 129, 256, 16383, 16384, 2_000_000, 44, 325]:
        v, off = read_varint(enc_varint(n), 0)
        assert v == n


# --- single-value decoding per serial type -----------------------------------

def test_decode_null():
    rec = decode_record(make_record([(0, b"")]))
    assert rec.values == [None]


def test_decode_1byte_int():
    rec = decode_record(make_record([(1, b"\x2a")]))
    assert rec.values == [42]


def test_decode_2byte_int():
    rec = decode_record(make_record([(2, struct.pack(">h", 1000))]))
    assert rec.values == [1000]


def test_decode_4byte_int_real_timestamp():
    # col10 LastModifiedTime serial 4 = 0x5fd07c9f from the real record
    rec = decode_record(make_record([(4, bytes.fromhex("5fd07c9f"))]))
    assert rec.values == [0x5FD07C9F]


def test_decode_negative_int():
    rec = decode_record(make_record([(1, b"\xff")]))      # -1 (1 byte signed)
    assert rec.values == [-1]
    rec = decode_record(make_record([(2, b"\xff\xfe")]))  # -2 (2 byte signed)
    assert rec.values == [-2]


def test_decode_6byte_int():
    raw = (123456789).to_bytes(6, "big")
    rec = decode_record(make_record([(5, raw)]))
    assert rec.values == [123456789]


def test_decode_float():
    rec = decode_record(make_record([(7, struct.pack(">d", 3.14))]))
    assert rec.values[0] == pytest.approx(3.14)


def test_decode_constant_zero_and_one():
    rec = decode_record(make_record([(8, b""), (9, b"")]))
    assert rec.values == [0, 1]


def test_decode_blob():
    guid = bytes(range(16))
    rec = decode_record(make_record([(44, guid)]))  # serial 44 -> 16-byte blob
    assert rec.values == [guid]
    assert isinstance(rec.values[0], bytes)


def test_decode_text_utf8():
    s = "Microsoft Edge"
    body = s.encode("utf-8")
    serial = 13 + 2 * len(body)  # odd -> text
    rec = decode_record(make_record([(serial, body)]))
    assert rec.values == [s]


# --- multi-column record -----------------------------------------------------

def test_decode_mixed_record():
    guid = bytes(range(16))
    rec = decode_record(
        make_record(
            [
                (44, guid),                 # Id blob
                (1, b"\x0b"),               # ActivityType = 11
                (9, b""),                   # ActivityStatus = 1 (constant)
                (4, bytes.fromhex("5fd07c9f")),  # timestamp
            ]
        )
    )
    assert rec.values == [guid, 11, 1, 0x5FD07C9F]
    assert rec.serial_types == [44, 1, 9, 4]


# --- real 31-column Activity header fingerprint ------------------------------

REAL_SERIALS = [44, 325, 101, 207, 1, 9, 44, 101, 117, 117, 4, 4, 36, 1, 8,
                101, 93, 4, 4, 8, 4, 13, 16, 13, 0, 8, 8, 0, 13, 8, 9]


def test_decode_real_activity_header_serials():
    # Build a header from the real serial types; bodies are zero-filled.
    from engine.varint import serial_type_size
    items = [(s, b"\x00" * serial_type_size(s)) for s in REAL_SERIALS]
    rec = decode_record(make_record(items))
    assert rec.serial_types == REAL_SERIALS
    assert len(rec.values) == 31
    assert rec.header_len == 34  # matches the real record's header_len


# --- table-leaf cell (payload_len + rowid + record) --------------------------

def test_decode_table_leaf_cell_no_overflow():
    guid = bytes(range(16))
    payload = make_record([(44, guid), (1, b"\x07")])
    cell = enc_varint(len(payload)) + enc_varint(42) + payload  # rowid 42
    page = b"\x00" * 100 + cell + b"\x00" * 100
    c = decode_table_leaf_cell(page, 100, usable_size=4096)
    assert isinstance(c, Cell)
    assert c.rowid == 42
    assert c.payload_len == len(payload)
    assert c.has_overflow is False
    assert c.values == [guid, 7]


# --- overflow threshold math -------------------------------------------------

def test_local_payload_size_no_overflow():
    usable = 4096
    local, has_ovf = local_payload_size(100, usable)
    assert has_ovf is False
    assert local == 100


def test_local_payload_size_overflow():
    usable = 4096
    # payload bigger than maxLocal (usable-35 = 4061) must overflow
    local, has_ovf = local_payload_size(10000, usable)
    assert has_ovf is True
    assert local < 10000
    # local must be within [minLocal, maxLocal]
    max_local = usable - 35
    min_local = ((usable - 12) * 32 // 255) - 23
    assert min_local <= local <= max_local


# --- try_decode_record: bounded, never-raises (for carving) ------------------

def test_try_decode_record_valid():
    from engine.record import try_decode_record
    guid = bytes(range(16))
    payload = make_record([(44, guid), (1, b"\x07"), (9, b"")])
    buf = b"\xAA\xBB" + payload + b"\xCC"
    view = try_decode_record(buf, 2, 2 + len(payload))
    assert view is not None
    assert view.serial_types == [44, 1, 9]
    assert view.values == [guid, 7, 1]
    assert view.truncated is False


def test_try_decode_record_truncated_body_returns_partial():
    from engine.record import try_decode_record
    guid = bytes(range(16))
    payload = make_record([(44, guid), (101, b"x" * 44)])  # 44-byte text col
    # cut the buffer so the second column's body is incomplete
    cut = len(payload) - 20
    view = try_decode_record(payload[:cut], 0, cut)
    assert view is not None
    assert view.truncated is True
    assert view.serial_types == [44, 101]
    assert view.values[0] == guid  # first column intact


def test_try_decode_record_absurd_header_len_returns_none():
    from engine.record import try_decode_record
    # header_len varint claims 9000 bytes but buffer is tiny
    buf = b"\xC6\x68" + b"\x00" * 4  # 0xC668 -> big varint
    assert try_decode_record(buf, 0, len(buf)) is None


def test_try_decode_record_truncated_header_returns_none():
    from engine.record import try_decode_record
    # continuation bit set on header_len varint but buffer ends
    assert try_decode_record(b"\x81", 0, 1) is None
