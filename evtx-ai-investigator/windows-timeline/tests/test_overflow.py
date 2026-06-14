"""Tests for overflow page chain reassembly (engine.overflow)."""

from __future__ import annotations

import struct

import pytest

from engine.overflow import reassemble_payload


class _MockPageSource:
    """Minimal PageSource stub backed by a dict of page_no → bytes."""

    def __init__(self, pages: dict[int, bytes], page_size: int = 4096):
        self.page_size = page_size
        self.usable_size = page_size
        self.page_count = max(pages.keys()) if pages else 0
        self._pages = pages

    def get_page(self, page_no: int) -> bytes:
        return self._pages.get(page_no, b"")


def _overflow_page(next_page: int, content: bytes, page_size: int = 4096) -> bytes:
    hdr = struct.pack(">I", next_page)
    payload = content[: page_size - 4]
    return hdr + payload + b"\x00" * (page_size - 4 - len(payload))


# ── Happy-path reassembly ─────────────────────────────────────────────────────

def test_single_overflow_page():
    data = b"A" * 500
    ps = _MockPageSource({2: _overflow_page(0, data)})
    result = reassemble_payload(2, 500, ps)
    assert result == data


def test_two_page_overflow_chain():
    page_size = 4096
    data_per = page_size - 4
    chunk1 = b"X" * data_per
    chunk2 = b"Y" * 200
    ps = _MockPageSource(
        {
            3: _overflow_page(4, chunk1, page_size),
            4: _overflow_page(0, chunk2, page_size),
        },
        page_size,
    )
    need = len(chunk1) + 200
    result = reassemble_payload(3, need, ps)
    assert result == chunk1 + chunk2


def test_need_bytes_caps_output():
    """Only need_bytes returned even when page has more data."""
    data = b"B" * 1000
    ps = _MockPageSource({5: _overflow_page(0, data)})
    result = reassemble_payload(5, 100, ps)
    assert result == data[:100]
    assert len(result) == 100


def test_exact_need_spanning_two_pages():
    page_size = 4096
    data_per = page_size - 4
    chunk1 = b"P" * data_per
    chunk2 = b"Q" * 50
    ps = _MockPageSource(
        {
            10: _overflow_page(11, chunk1, page_size),
            11: _overflow_page(0, chunk2, page_size),
        },
        page_size,
    )
    result = reassemble_payload(10, data_per + 50, ps)
    assert result == chunk1 + chunk2


# ── Edge cases and error handling ─────────────────────────────────────────────

def test_zero_need_returns_empty():
    ps = _MockPageSource({1: _overflow_page(0, b"data")})
    assert reassemble_payload(1, 0, ps) == b""


def test_invalid_first_page_zero():
    ps = _MockPageSource({1: _overflow_page(0, b"data")})
    assert reassemble_payload(0, 100, ps) == b""


def test_out_of_range_first_page_returns_empty():
    ps = _MockPageSource({1: _overflow_page(0, b"data")})
    result = reassemble_payload(99999, 100, ps)
    assert isinstance(result, bytes)
    assert result == b""


def test_missing_page_returns_partial():
    """Chain referencing a missing page returns whatever was gathered so far."""
    page_size = 4096
    data_per = page_size - 4
    chunk1 = b"Z" * data_per
    # Page 7 points to page 8, which doesn't exist
    ps = _MockPageSource({7: _overflow_page(8, chunk1, page_size)}, page_size)
    result = reassemble_payload(7, data_per + 500, ps)
    assert result == chunk1  # got chunk1, then chain broke


def test_cycle_terminates():
    """Self-referential chain terminates without infinite loop."""
    page_size = 4096
    # Page 2 points to itself
    ps = _MockPageSource({2: _overflow_page(2, b"C" * 100, page_size)}, page_size)
    result = reassemble_payload(2, 10000, ps)
    assert isinstance(result, bytes)
    assert len(result) <= 10000


def test_short_page_data_stops_chain():
    """A page with fewer than 4 bytes stops reassembly gracefully."""
    ps = _MockPageSource({3: b"\x00\x00"})  # only 2 bytes — too short for header
    result = reassemble_payload(3, 100, ps)
    assert result == b""


# ── Integration: real overflow via padded DB ──────────────────────────────────

def test_real_overflow_chain(tmp_path):
    """With large Payload padding, at least one cell overflows; chain is complete."""
    import struct as _struct
    from engine.pages import PageSource
    from engine.overflow import reassemble_payload as _rp
    from engine.record import try_read_varint, local_payload_size
    from engine.sqlite_format import parse_page_header, LEAF_TABLE
    from tests.conftest import build_activity_db

    path = str(tmp_path / "padded.db")
    build_activity_db(path, n_insert=5, payload_pad=5000)
    ps = PageSource.from_file(path)

    found = False
    for pg_no in range(1, ps.page_count + 1):
        page = ps.get_page(pg_no)
        type_off = 100 if pg_no == 1 else 0
        if len(page) <= type_off or page[type_off] != LEAF_TABLE:
            continue
        try:
            header = parse_page_header(page, pg_no, ps.page_size)
        except Exception:
            continue
        for i in range(header.num_cells):
            ptr_off = header.cell_ptr_array_offset + i * 2
            if ptr_off + 2 > ps.usable_size:
                break
            cell_off = int.from_bytes(page[ptr_off : ptr_off + 2], "big")
            # table-leaf cell: payload_len varint | rowid varint | payload [| overflow_pgno]
            pv = try_read_varint(page, cell_off, ps.usable_size)
            if pv is None:
                continue
            payload_len, p1 = pv
            rv = try_read_varint(page, p1, ps.usable_size)  # consume rowid
            if rv is None:
                continue
            _, p2 = rv  # p2 = start of payload bytes
            local_len, has_overflow = local_payload_size(payload_len, ps.usable_size)
            if not has_overflow:
                continue
            if p2 + local_len + 4 > len(page):
                continue
            first_overflow = _struct.unpack(
                ">I", page[p2 + local_len : p2 + local_len + 4]
            )[0]
            need = payload_len - local_len
            result = _rp(first_overflow, need, ps)
            assert len(result) == need, f"overflow chain incomplete: got {len(result)}/{need}"
            found = True
            break
        if found:
            break

    assert found, "Expected overflow cells in padded DB (payload_pad=5000)"
