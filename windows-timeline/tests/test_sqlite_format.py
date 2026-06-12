"""Tests for engine.sqlite_format (DB header + B-tree page header parsing)."""

import struct

import pytest

from engine.sqlite_format import (
    MAGIC,
    LEAF_TABLE,
    INTERIOR_TABLE,
    DBHeader,
    PageHeader,
    parse_db_header,
    parse_page_header,
)

# A real, captured ActivitiesCache.db first-100-bytes header (fixed vector).
REAL_HDR = bytes.fromhex(
    "53514c69746520666f726d617420330010000202004020200000005c00000a8f0000081e000002c300000019000000040000000000000000000000010000001e000000000000000000000000000000000000000000000000000000000000005c002e8df9"
)


def test_real_header_len_is_100():
    assert len(REAL_HDR) == 100


def test_parse_db_header_real_vector():
    h = parse_db_header(REAL_HDR)
    assert isinstance(h, DBHeader)
    assert h.page_size == 4096
    assert h.reserved == 0
    assert h.write_format == 2
    assert h.read_format == 2
    assert h.file_change_counter == 92
    assert h.db_size_pages == 2703
    assert h.first_freelist_trunk == 2078
    assert h.freelist_count == 707
    assert h.schema_cookie == 25
    assert h.text_encoding == 1
    assert h.version_valid_for == 92
    assert h.sqlite_version == 3051001


def test_usable_size_subtracts_reserved():
    h = parse_db_header(REAL_HDR)
    assert h.usable_size == 4096  # reserved == 0


def test_encoding_name():
    h = parse_db_header(REAL_HDR)
    assert h.encoding_name == "UTF-8"


def test_header_db_size_trustworthy_when_counters_match():
    # change_counter (92) == version_valid_for (92) -> db_size_pages is trustworthy
    h = parse_db_header(REAL_HDR)
    assert h.db_size_trustworthy is True


def test_parse_db_header_rejects_bad_magic():
    bad = b"NotSQLite\x00" + REAL_HDR[10:]
    with pytest.raises(ValueError):
        parse_db_header(bad)


def test_page_size_value_one_means_65536():
    hdr = bytearray(REAL_HDR)
    hdr[16:18] = struct.pack(">H", 1)  # special encoding for 65536
    h = parse_db_header(bytes(hdr))
    assert h.page_size == 65536


def test_magic_constant():
    assert MAGIC == b"SQLite format 3\x00"
    assert REAL_HDR.startswith(MAGIC)


# --- page headers ------------------------------------------------------------

def _leaf_page(first_freeblock=0, num_cells=3, content_start=4000, frag=0,
               page_size=4096):
    body = bytes([LEAF_TABLE]) + struct.pack(
        ">HHHB", first_freeblock, num_cells, content_start, frag
    )
    return body + b"\x00" * (page_size - len(body))


def _interior_page(first_freeblock=0, num_cells=5, content_start=3000, frag=0,
                   right_most=99, page_size=4096):
    body = bytes([INTERIOR_TABLE]) + struct.pack(
        ">HHHB", first_freeblock, num_cells, content_start, frag
    ) + struct.pack(">I", right_most)
    return body + b"\x00" * (page_size - len(body))


def test_parse_leaf_page_header():
    page = _leaf_page(first_freeblock=120, num_cells=3, content_start=4000, frag=2)
    ph = parse_page_header(page, page_no=5, page_size=4096)
    assert isinstance(ph, PageHeader)
    assert ph.page_type == LEAF_TABLE
    assert ph.first_freeblock == 120
    assert ph.num_cells == 3
    assert ph.cell_content_start == 4000
    assert ph.num_frag_free == 2
    assert ph.right_most_pointer is None
    assert ph.header_len == 8
    assert ph.cell_ptr_array_offset == 8
    assert ph.is_leaf is True


def test_parse_interior_page_header_has_right_pointer():
    page = _interior_page(num_cells=5, right_most=12345)
    ph = parse_page_header(page, page_no=2, page_size=4096)
    assert ph.page_type == INTERIOR_TABLE
    assert ph.num_cells == 5
    assert ph.right_most_pointer == 12345
    assert ph.header_len == 12
    assert ph.cell_ptr_array_offset == 12
    assert ph.is_leaf is False


def test_page_one_header_offset_is_100():
    # Page 1 carries the 100-byte DB header prefix, so its page header
    # begins at byte 100. Build a page whose b-tree header lives there.
    page = bytearray(REAL_HDR) + bytearray(4096 - 100)
    page[100] = LEAF_TABLE
    page[101:108] = struct.pack(">HHHB", 0, 7, 3500, 0)
    ph = parse_page_header(bytes(page), page_no=1, page_size=4096)
    assert ph.page_type == LEAF_TABLE
    assert ph.num_cells == 7
    assert ph.cell_content_start == 3500
    assert ph.cell_ptr_array_offset == 108  # 100 + 8


def test_cell_content_start_zero_means_65536():
    page = _leaf_page(content_start=0, page_size=4096)
    ph = parse_page_header(page, page_no=5, page_size=4096)
    assert ph.cell_content_start == 65536
