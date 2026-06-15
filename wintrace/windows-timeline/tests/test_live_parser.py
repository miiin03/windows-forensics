"""Tests for engine.live_parser (allocated-record reading via sqlite3)."""

from engine.live_parser import read_activity, LiveRecord


def test_reads_all_live_rows(make_activity_db):
    gt = make_activity_db(n_insert=10, m_delete=3)
    records = read_activity(gt["db_path"])
    assert len(records) == len(gt["live"]) == 7
    got_guids = {r.values["Id"] for r in records}
    assert got_guids == set(gt["live"])


def test_record_shape(make_activity_db):
    gt = make_activity_db(n_insert=5, m_delete=0)
    records = read_activity(gt["db_path"])
    r = records[0]
    assert isinstance(r, LiveRecord)
    assert r.table == "Activity"
    assert r.source == "live"
    assert isinstance(r.values["Id"], bytes)
    assert len(r.values["Id"]) == 16
    assert isinstance(r.values["AppId"], str)
    assert r.values["AppId"].startswith("[{")
    assert isinstance(r.values["Payload"], bytes)
    assert isinstance(r.values["LastModifiedTime"], int)
    assert isinstance(r.rowid, int)


def test_deleted_rows_absent_from_live(make_activity_db):
    gt = make_activity_db(n_insert=20, m_delete=5)
    records = read_activity(gt["db_path"])
    got = {r.values["Id"] for r in records}
    for d in gt["deleted"]:
        assert d not in got
