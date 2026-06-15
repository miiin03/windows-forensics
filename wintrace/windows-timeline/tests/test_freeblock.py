"""Tests for in-page freeblock carving."""

from engine.carver.freeblock import carve_freeblocks
from engine.pages import PageSource


def _guid_set(cells):
    return {c.values[0] for c in cells if c.values and isinstance(c.values[0], bytes)}


def test_freeblocks_carve_deleted_records_from_allocated_leaf_page(make_activity_db):
    deleted_indices = [150, 151, 152]
    gt = make_activity_db(
        n_insert=180,
        m_delete=len(deleted_indices),
        delete_indices=deleted_indices,
    )
    ps = PageSource.from_file(gt["db_path"])

    cells = carve_freeblocks(ps)

    assert ps.header.freelist_count == 0
    assert set(gt["deleted"]) <= _guid_set(cells)
    assert all(c.source == "freeblock" for c in cells)
    assert all(c.rowid is None for c in cells)


def test_freeblocks_return_no_records_when_secure_delete_zeroes_cells(make_activity_db):
    deleted_indices = [150, 151, 152]
    gt = make_activity_db(
        n_insert=180,
        m_delete=len(deleted_indices),
        delete_indices=deleted_indices,
        secure_delete=True,
    )
    ps = PageSource.from_file(gt["db_path"])

    assert carve_freeblocks(ps) == []
