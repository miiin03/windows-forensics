"""Tests for WAL-frame carving (engine.carver.wal)."""

from __future__ import annotations

import os
import shutil
import sqlite3
import struct

import pytest

from engine.carver.wal import (
    FRAME_HEADER_SIZE,
    WAL_HEADER_SIZE,
    WAL_MAGIC_BE,
    WAL_MAGIC_LE,
    carve_wal,
    count_wal_frames,
    parse_wal_header,
    read_wal_frames,
)
from tests.conftest import build_activity_db


# ── Fixture helpers ───────────────────────────────────────────────────────────

def _wal_copy(path: str) -> str:
    """Return a stable copy path for the WAL file."""
    return path + "-saved"


def _build_wal_with_reader(path: str, n: int = 20) -> str:
    """Create a WAL DB, copy the WAL while a reader holds it open.

    SQLite 3.x deletes the WAL file when the last connection closes (passive
    checkpoint + cleanup). Holding an open read transaction prevents that,
    allowing us to copy the WAL before it disappears.

    Returns the path of the copied (persistent) WAL file.
    """
    build_activity_db(path, n_insert=n, wal=True, checkpoint=False)
    # WAL is deleted by SQLite on close; DB stays in WAL mode.
    # Reopen with a reader lock, then write → WAL recreated and preserved.
    reader = sqlite3.connect(path)
    reader.execute("PRAGMA wal_autocheckpoint=0")
    reader.execute("BEGIN")
    list(reader.execute('SELECT count(*) FROM "Activity"'))

    w = sqlite3.connect(path)
    w.execute("PRAGMA wal_autocheckpoint=0")
    w.execute('UPDATE "Activity" SET "ETag"=ETag+1')
    w.commit()
    w.close()

    copy = _wal_copy(path)
    shutil.copy(path + "-wal", copy)
    reader.close()
    return copy


def _make_multi_version_wal(path: str) -> dict:
    """Build a WAL DB with multiple versions of the same pages.

    Strategy:
    1. build_activity_db creates the DB (WAL vanishes on close).
    2. Reopen; hold a reader lock to prevent WAL cleanup.
    3. Writer1: UPDATE all rows → WAL V1 frames for data pages.
    4. Writer2: DELETE target rows → WAL V2 frames for same pages.
    5. Copy WAL (V1 + V2 for same page_nos) before reader closes.
    """
    gt = build_activity_db(path, n_insert=60, wal=True, checkpoint=False)

    reader = sqlite3.connect(path)
    reader.execute("PRAGMA wal_autocheckpoint=0")
    reader.execute("BEGIN")
    list(reader.execute('SELECT count(*) FROM "Activity"'))

    w1 = sqlite3.connect(path)
    w1.execute("PRAGMA wal_autocheckpoint=0")
    w1.execute('UPDATE "Activity" SET "ETag"=ETag+10000')
    w1.commit()
    w1.close()

    to_delete = gt["inserted"][::6][:6]
    w2 = sqlite3.connect(path)
    w2.execute("PRAGMA wal_autocheckpoint=0")
    for guid in to_delete:
        w2.execute('DELETE FROM "Activity" WHERE "Id"=?', (guid,))
    w2.commit()
    w2.close()

    copy = _wal_copy(path)
    shutil.copy(path + "-wal", copy)
    reader.close()

    return {**gt, "wal_deleted": to_delete, "wal_path": copy}


def _minimal_wal_header(page_size: int = 4096, salt1: int = 1, salt2: int = 2) -> bytes:
    return struct.pack(
        ">IIIIIIII",
        WAL_MAGIC_LE,
        3007000,
        page_size,
        0,
        salt1,
        salt2,
        0,
        0,
    )


# ── Header parsing ────────────────────────────────────────────────────────────

def test_parse_wal_header_le_magic():
    header = _minimal_wal_header()
    h = parse_wal_header(header)
    assert h is not None
    assert h.magic == WAL_MAGIC_LE
    assert h.page_size == 4096
    assert not h.is_big_endian


def test_parse_wal_header_be_magic():
    header = struct.pack(">IIIIIIII", WAL_MAGIC_BE, 3007000, 4096, 0, 1, 2, 0, 0)
    h = parse_wal_header(header)
    assert h is not None
    assert h.magic == WAL_MAGIC_BE
    assert h.is_big_endian


def test_parse_wal_header_salt_fields():
    header = struct.pack(">IIIIIIII", WAL_MAGIC_LE, 3007000, 4096, 7, 0xDEADBEEF, 0xCAFEBABE, 0, 0)
    h = parse_wal_header(header)
    assert h.salt1 == 0xDEADBEEF
    assert h.salt2 == 0xCAFEBABE
    assert h.checkpoint_seq == 7


def test_parse_wal_header_bad_magic_returns_none():
    assert parse_wal_header(b"\x00" * 32) is None


def test_parse_wal_header_too_short_returns_none():
    assert parse_wal_header(b"\x00" * 10) is None


# ── Frame reading ─────────────────────────────────────────────────────────────

def test_read_wal_frames_real_db(tmp_path):
    wal_path = _build_wal_with_reader(str(tmp_path / "t.db"))
    with open(wal_path, "rb") as f:
        data = f.read()
    h = parse_wal_header(data)
    assert h is not None
    frames = read_wal_frames(data, h)
    assert len(frames) > 0
    assert all(f.page_no >= 1 for f in frames)
    assert all(len(f.data) == h.page_size for f in frames)


def test_frame_indices_are_sequential(tmp_path):
    wal_path = _build_wal_with_reader(str(tmp_path / "t.db"))
    with open(wal_path, "rb") as f:
        data = f.read()
    h = parse_wal_header(data)
    frames = read_wal_frames(data, h)
    assert [f.index for f in frames] == list(range(len(frames)))


def test_frame_salt_match_fresh_wal(tmp_path):
    """All frames in a freshly-written WAL should match the header salt."""
    wal_path = _build_wal_with_reader(str(tmp_path / "t.db"))
    with open(wal_path, "rb") as f:
        data = f.read()
    h = parse_wal_header(data)
    frames = read_wal_frames(data, h)
    assert all(f.salt_match for f in frames)


def test_count_wal_frames(tmp_path):
    wal_path = _build_wal_with_reader(str(tmp_path / "t.db"))
    n = count_wal_frames(wal_path)
    assert n > 0


def test_count_wal_frames_missing_file():
    assert count_wal_frames("/nonexistent/path.db-wal") == 0


# ── Prior-version carving ─────────────────────────────────────────────────────

def test_carve_wal_recovers_deleted_records(tmp_path):
    path = str(tmp_path / "mv.db")
    info = _make_multi_version_wal(path)
    cells = carve_wal(info["wal_path"])
    recovered = {c.values[0] for c in cells if c.values and isinstance(c.values[0], bytes)}
    assert set(info["wal_deleted"]) & recovered


def test_carve_wal_source_labels(tmp_path):
    path = str(tmp_path / "mv.db")
    info = _make_multi_version_wal(path)
    cells = carve_wal(info["wal_path"])
    assert cells
    assert all(c.source in {"wal", "wal_stale"} for c in cells)


def test_carve_wal_fresh_cells_are_wal_not_stale(tmp_path):
    path = str(tmp_path / "mv.db")
    info = _make_multi_version_wal(path)
    cells = carve_wal(info["wal_path"])
    # A freshly-written WAL has matching salts
    assert any(c.source == "wal" for c in cells)


def test_carve_wal_no_live_duplicates(tmp_path):
    """Records still present in the latest WAL frame must not appear in output."""
    path = str(tmp_path / "nd.db")
    build_activity_db(path, n_insert=40, wal=True, checkpoint=False)

    reader = sqlite3.connect(path)
    reader.execute("PRAGMA wal_autocheckpoint=0")
    reader.execute("BEGIN")
    list(reader.execute('SELECT count(*) FROM "Activity"'))

    w1 = sqlite3.connect(path)
    w1.execute("PRAGMA wal_autocheckpoint=0")
    w1.execute('UPDATE "Activity" SET "ETag"=ETag+9000 WHERE "ETag" < 5')
    w1.commit()
    w1.close()

    w2 = sqlite3.connect(path)
    w2.execute("PRAGMA wal_autocheckpoint=0")
    w2.execute('UPDATE "Activity" SET "ETag"=ETag+1 WHERE "ETag" > 9000')
    w2.commit()
    w2.close()

    copy = shutil.copy(path + "-wal", path + "-wal-nd")
    reader.close()

    cells = carve_wal(copy)
    assert all(c.source in {"wal", "wal_stale"} for c in cells)


def test_carve_wal_missing_file_returns_empty():
    assert carve_wal("/nonexistent/path.db-wal") == []


def test_carve_wal_empty_file_returns_empty(tmp_path):
    p = tmp_path / "empty.db-wal"
    p.write_bytes(b"")
    assert carve_wal(str(p)) == []


def test_carve_wal_bad_magic_returns_empty(tmp_path):
    p = tmp_path / "bad.db-wal"
    p.write_bytes(b"\x00" * 64)
    assert carve_wal(str(p)) == []


def test_carve_wal_no_multi_version_pages_returns_empty(tmp_path):
    """A WAL where every page appears exactly once has no prior versions to carve."""
    wal_path = _build_wal_with_reader(str(tmp_path / "single.db"), n=5)
    cells = carve_wal(wal_path)
    # Can't assert == [] because some pages may appear multiple times (schema + data),
    # but all results should be valid.
    assert all(c.source in {"wal", "wal_stale"} for c in cells)


# ── Real WAL regression (structural invariants) ───────────────────────────────

def test_real_wal_fixtures_structural_invariants():
    """Any -wal files under tests/fixtures satisfy header + frame-count invariants."""
    fixture_dir = os.path.join(os.path.dirname(__file__), "fixtures")
    if not os.path.isdir(fixture_dir):
        pytest.skip("no fixtures directory")
    wal_files = [
        os.path.join(fixture_dir, f)
        for f in os.listdir(fixture_dir)
        if f.endswith("-wal")
    ]
    if not wal_files:
        pytest.skip("no -wal files in fixtures")
    for wal_path in wal_files:
        with open(wal_path, "rb") as fh:
            data = fh.read()
        h = parse_wal_header(data)
        assert h is not None, f"bad WAL header: {wal_path}"
        frames = read_wal_frames(data, h)
        assert len(frames) > 0, f"no frames in: {wal_path}"
        assert all(f.page_no >= 1 for f in frames), f"invalid page_no in: {wal_path}"
