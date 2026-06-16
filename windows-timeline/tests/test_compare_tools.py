import csv as c

from engine.live_parser import read_activity
from bench.compare_tools import compare_live_with_wxtcmd_csv


def _write_wxtcmd_csv(path, guids_hex, header="Id"):
    with open(path, "w", newline="") as f:
        w = c.writer(f)
        w.writerow([header])
        for g in guids_hex:
            w.writerow([g])


def test_live_count_matches_wxtcmd(make_activity_db, tmp_path):
    gt = make_activity_db(n_insert=30, m_delete=0)
    ours = read_activity(gt["db_path"])
    csv_path = tmp_path / "wx.csv"
    _write_wxtcmd_csv(csv_path, [r.values["Id"].hex() for r in ours])

    res = compare_live_with_wxtcmd_csv(gt["db_path"], str(csv_path))
    assert res["match"] is True
    assert res["ours_count"] == res["wxtcmd_count"] == 30
    assert res["only_ours"] == []
    assert res["only_wxtcmd"] == []


def test_mismatch_reports_differences(make_activity_db, tmp_path):
    gt = make_activity_db(n_insert=10, m_delete=0)
    ours = read_activity(gt["db_path"])
    hexes = [r.values["Id"].hex() for r in ours]
    # WxTCmd missed one of ours and invented one extra.
    csv_path = tmp_path / "wx.csv"
    _write_wxtcmd_csv(csv_path, hexes[:-1] + ["ff" * 16])

    res = compare_live_with_wxtcmd_csv(gt["db_path"], str(csv_path))
    assert res["match"] is False
    assert res["ours_count"] == 10
    assert res["wxtcmd_count"] == 10
    assert len(res["only_ours"]) == 1  # the GUID WxTCmd missed
    assert len(res["only_wxtcmd"]) == 1  # the GUID only WxTCmd has


def test_dashed_guid_column_autodetected(make_activity_db, tmp_path):
    gt = make_activity_db(n_insert=5, m_delete=0)
    ours = read_activity(gt["db_path"])
    # Real WxTCmd uses a dashed/braced GUID under a differently-named column.
    def dash(h):
        return f"{{{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}}}".upper()

    csv_path = tmp_path / "wx.csv"
    _write_wxtcmd_csv(csv_path, [dash(r.values["Id"].hex()) for r in ours], header="ActivityId")

    res = compare_live_with_wxtcmd_csv(gt["db_path"], str(csv_path))
    assert res["match"] is True
    assert res["ours_count"] == res["wxtcmd_count"] == 5
