"""Tests for engine.carver.base (cell -> CarvedCell with validation)."""

from engine.pages import PageSource
from engine.sqlite_format import parse_page_header
from engine.carver.base import carve_full_cell, carve_record_fragment, CarvedCell


def _first_cell_pointer(page, page_no, page_size):
    ph = parse_page_header(page, page_no, page_size)
    ptr_off = ph.cell_ptr_array_offset
    return int.from_bytes(page[ptr_off : ptr_off + 2], "big"), ph.num_cells


def test_carve_full_cell_recovers_activity_record(make_activity_db):
    gt = make_activity_db(n_insert=8, m_delete=0)
    ps = PageSource.from_file(gt["db_path"])
    page2 = ps.get_page(2)  # Activity leaf
    cptr, ncells = _first_cell_pointer(page2, 2, ps.page_size)
    cc = carve_full_cell(page2, cptr, ps.usable_size, "freelist", 2, ps.page_size)
    assert isinstance(cc, CarvedCell)
    assert cc.table == "Activity"
    assert cc.source == "freelist"
    assert isinstance(cc.values[0], bytes) and len(cc.values[0]) == 16
    assert cc.values[0] in set(gt["live"])
    assert cc.confidence > 0
    assert cc.byte_range[0] < cc.byte_range[1]


def test_carve_full_cell_rejects_garbage_offset(make_activity_db):
    gt = make_activity_db(n_insert=8, m_delete=0)
    ps = PageSource.from_file(gt["db_path"])
    page2 = ps.get_page(2)
    # offset into the middle of the page header / random area -> not a cell
    assert carve_full_cell(page2, 1, ps.usable_size, "freelist", 2, ps.page_size) is None


def test_carve_record_fragment_recovers_without_rowid(make_activity_db):
    gt = make_activity_db(n_insert=8, m_delete=0)
    ps = PageSource.from_file(gt["db_path"])
    page2 = ps.get_page(2)
    cptr, _ = _first_cell_pointer(page2, 2, ps.page_size)
    # the record starts after the payload_len + rowid varints; emulate a freeblock
    # by pointing the fragment carver at the record header directly.
    from engine.varint import read_varint
    _, p1 = read_varint(page2, cptr)
    _, rec_start = read_varint(page2, p1)
    cc = carve_record_fragment(page2, rec_start, ps.page_size, "freeblock", 2, ps.page_size)
    assert isinstance(cc, CarvedCell)
    assert cc.rowid is None
    assert cc.source == "freeblock"
    assert cc.values[0] in set(gt["live"])
