"""Tests for freelist-page carving."""

from engine.carver.freelist import carve_freelist, freelist_page_numbers
from engine.pages import PageSource


def _guid_set(cells):
    return {c.values[0] for c in cells if c.values and isinstance(c.values[0], bytes)}


def test_freelist_carves_deleted_records_from_freed_leaf_pages(make_activity_db):
    gt = make_activity_db(n_insert=200, m_delete=150)
    ps = PageSource.from_file(gt["db_path"])

    trunk_pages, leaf_pages = freelist_page_numbers(ps)
    cells = carve_freelist(ps)

    assert ps.header.freelist_count > 0
    assert trunk_pages
    assert leaf_pages
    assert set(gt["deleted"]) & _guid_set(cells)
    assert all(c.source in {"freelist", "freelist_brute"} for c in cells)


def test_freelist_returns_no_records_after_vacuum(make_activity_db):
    gt = make_activity_db(n_insert=200, m_delete=150, vacuum=True)
    ps = PageSource.from_file(gt["db_path"])

    assert ps.header.freelist_count == 0
    assert carve_freelist(ps) == []
