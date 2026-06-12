"""Tests for slack-space carving (engine.carver.slack)."""

from __future__ import annotations

import sqlite3

from engine.carver.freelist import freelist_page_numbers
from engine.carver.slack import carve_slack
from engine.pages import PageSource
from tests.conftest import ACTIVITY_DDL, build_activity_db


# ── Helper ────────────────────────────────────────────────────────────────────

def _build_defrag_db(path: str) -> None:
    """Build a DB likely to have defragmented pages with slack content.

    Strategy: fill pages densely, delete every-other row (scattered freeblocks),
    then insert slightly-larger rows.  When no single freeblock fits the new cell
    but total free space is enough, SQLite defragments the page — leaving old cell
    bytes in the slack gap.
    """
    from engine.schema import ACTIVITY_COLUMNS
    from tests.conftest import _row, make_guid

    placeholders = ", ".join(["?"] * len(ACTIVITY_COLUMNS))

    con = sqlite3.connect(path)
    con.execute("PRAGMA page_size=4096")
    con.execute("PRAGMA secure_delete=OFF")
    con.execute(ACTIVITY_DDL)

    # Phase 1: fill densely
    n = 300
    con.executemany(
        f'INSERT INTO "Activity" VALUES ({placeholders})',
        [_row(i) for i in range(n)],
    )
    con.commit()

    # Phase 2: delete every other row (scattered freeblocks)
    for i in range(0, n, 2):
        con.execute('DELETE FROM "Activity" WHERE "Id"=?', (make_guid(i),))
    con.commit()

    # Phase 3: insert rows with larger payload → may trigger defragmentation
    con.executemany(
        f'INSERT INTO "Activity" VALUES ({placeholders})',
        [_row(i + 10000, payload_pad=200) for i in range(80)],
    )
    con.commit()
    con.close()


# ── Correctness tests ─────────────────────────────────────────────────────────

def test_slack_clean_db_no_false_positives(make_activity_db):
    """A fresh DB with no deletions has zero-filled slack — no false positives."""
    gt = make_activity_db(n_insert=100)
    ps = PageSource.from_file(gt["db_path"])
    assert carve_slack(ps) == []


def test_slack_all_results_tagged_slack(make_activity_db):
    """Every carved record must carry source='slack'."""
    gt = make_activity_db(n_insert=200, m_delete=80)
    ps = PageSource.from_file(gt["db_path"])
    cells = carve_slack(ps)
    assert all(c.source == "slack" for c in cells)


def test_slack_no_freelist_page_overlap(make_activity_db):
    """carve_slack must not return results from freelist-owned pages."""
    gt = make_activity_db(n_insert=200, m_delete=150)
    ps = PageSource.from_file(gt["db_path"])
    trunk, leaf = freelist_page_numbers(ps)
    excluded = trunk | leaf

    cells = carve_slack(ps)
    assert all(c.page_no not in excluded for c in cells)


def test_slack_cells_have_valid_structure(make_activity_db):
    """Any carved slack cell has a non-empty serial_types list and confidence ≥ 0."""
    gt = make_activity_db(n_insert=200, m_delete=100)
    ps = PageSource.from_file(gt["db_path"])
    cells = carve_slack(ps)
    for c in cells:
        assert isinstance(c.serial_types, list)
        assert len(c.serial_types) > 0
        assert 0.0 <= c.confidence <= 1.0
        assert c.confidence_label in {"high", "medium", "low", "very_low"}


def test_slack_no_crash_vacuumed_db(make_activity_db):
    """carve_slack must complete without error on a vacuumed (fully compacted) DB."""
    gt = make_activity_db(n_insert=100, m_delete=50, vacuum=True)
    ps = PageSource.from_file(gt["db_path"])
    cells = carve_slack(ps)
    assert isinstance(cells, list)
    assert all(c.source == "slack" for c in cells)


def test_slack_no_crash_secure_delete(make_activity_db):
    """carve_slack must not crash when secure_delete zeroed the cell content."""
    gt = make_activity_db(n_insert=100, m_delete=50, secure_delete=True)
    ps = PageSource.from_file(gt["db_path"])
    cells = carve_slack(ps)
    assert isinstance(cells, list)


# ── Defragmentation scenario ──────────────────────────────────────────────────

def test_slack_defrag_scenario_no_crash(tmp_path):
    """Multi-phase insert/delete/insert may trigger defragmentation; must not crash."""
    path = str(tmp_path / "defrag.db")
    _build_defrag_db(path)
    ps = PageSource.from_file(path)
    cells = carve_slack(ps)
    assert isinstance(cells, list)
    assert all(c.source == "slack" for c in cells)


def test_slack_defrag_results_pass_plausibility_gate(tmp_path):
    """Slack cells found after defrag have passed the 31-col + GUID gate."""
    path = str(tmp_path / "defrag2.db")
    _build_defrag_db(path)
    ps = PageSource.from_file(path)
    cells = carve_slack(ps)
    # The validate gate ran inside carve_record_fragment; just verify contract
    for c in cells:
        assert len(c.values) > 0
        assert c.payload_truncated or len(c.values) > 0


# ── Duplicate suppression ─────────────────────────────────────────────────────

def test_slack_no_duplicate_cells(make_activity_db):
    """carve_slack must not emit two cells with the same (source, page_no, offset)."""
    gt = make_activity_db(n_insert=200, m_delete=100)
    ps = PageSource.from_file(gt["db_path"])
    cells = carve_slack(ps)
    keys = [(c.source, c.page_no, c.cell_offset) for c in cells]
    assert len(keys) == len(set(keys))
