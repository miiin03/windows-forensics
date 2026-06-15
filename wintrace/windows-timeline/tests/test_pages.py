"""Tests for engine.pages (page source abstraction)."""

from engine.pages import PageSource
from engine.sqlite_format import MAGIC


def test_from_file_reads_header_and_pages(make_activity_db):
    gt = make_activity_db(n_insert=50, m_delete=0, payload_pad=100)
    ps = PageSource.from_file(gt["db_path"])
    assert ps.page_size == 4096
    assert ps.page_count >= 1
    page1 = ps.get_page(1)
    assert len(page1) == 4096
    assert page1.startswith(MAGIC)


def test_get_page_is_one_based(make_activity_db):
    gt = make_activity_db(n_insert=5, m_delete=0)
    ps = PageSource.from_file(gt["db_path"])
    # page 1 holds the DB header; page 2 does not start with MAGIC
    assert ps.get_page(1).startswith(MAGIC)
    assert not ps.get_page(2).startswith(MAGIC)


def test_wal_overlay_takes_precedence():
    header_data = bytearray(b"\x00" * 4096 * 3)
    header_data[:16] = MAGIC
    header_data[16:18] = (4096).to_bytes(2, "big")
    header_data[56:60] = (1).to_bytes(4, "big")
    overlay = {2: b"\xAA" * 4096}
    ps = PageSource(bytes(header_data), _parse(bytes(header_data)), wal_overlay=overlay)
    assert ps.get_page(2, use_wal=True) == b"\xAA" * 4096
    assert ps.get_page(2, use_wal=False) != b"\xAA" * 4096


def _parse(data):
    from engine.sqlite_format import parse_db_header
    return parse_db_header(data[:100])
