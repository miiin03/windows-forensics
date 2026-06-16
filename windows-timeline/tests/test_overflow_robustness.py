"""A broken/out-of-range overflow chain must degrade to a truncated record,
never raise. Regression for the wintrace-integration "OSError on some records".
"""

import struct

from engine.record import Cell, decode_table_leaf_cell, local_payload_size


def _enc_varint(n: int) -> bytes:
    if n == 0:
        return b"\x00"
    out = []
    while n:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out[0] &= 0x7F
    return bytes(reversed(out))


def _make_record(cols) -> bytes:
    serials = b"".join(_enc_varint(s) for s, _ in cols)
    header_len = len(serials) + 1
    hl = _enc_varint(header_len)
    if len(hl) != 1:
        header_len = len(serials) + len(hl)
        hl = _enc_varint(header_len)
    return hl + serials + b"".join(b for _, b in cols)


def _overflow_cell(usable: int):
    """A cell that overflows, where a float column lives past the local payload."""
    text = b"A" * 600
    payload = _make_record([(2 * len(text) + 13, text), (7, struct.pack(">d", 2.5))])
    payload_len = usable * 3  # force has_overflow
    local_len, has_ovf = local_payload_size(payload_len, usable)
    assert has_ovf
    local_payload = payload[:local_len]  # float column NOT present locally
    cell = _enc_varint(payload_len) + _enc_varint(42) + local_payload + struct.pack(">I", 999999)
    return b"\x00" * 100 + cell + b"\x00" * 100, 100


def test_overflow_out_of_range_does_not_raise():
    usable = 4096
    page, off = _overflow_cell(usable)

    def reader(first_page, need):  # out-of-range / broken chain recovers nothing
        return b""

    c = decode_table_leaf_cell(page, off, usable_size=usable, overflow_reader=reader)
    assert isinstance(c, Cell)
    assert c.payload_truncated is True
    assert c.rowid == 42
    assert c.first_overflow_page == 999999  # recorded for forensics even when unreachable


def test_overflow_reader_raising_is_contained():
    usable = 4096
    page, off = _overflow_cell(usable)

    def reader(first_page, need):  # a reader that itself blows up must not propagate
        raise OSError("simulated read failure")

    c = decode_table_leaf_cell(page, off, usable_size=usable, overflow_reader=reader)
    assert c.payload_truncated is True
