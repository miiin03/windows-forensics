from engine.cli import build_parser, run


def test_output_meta_has_evidence_hashes(make_activity_db, tmp_path):
    gt = make_activity_db(n_insert=20, m_delete=5)
    args = build_parser().parse_args([gt["db_path"], "--ui", "-o", str(tmp_path / "r.json")])
    d = run(args)
    ev = d["meta"]["evidence"]  # list of custody records
    assert any(e["path"].endswith("ActivitiesCache.db") for e in ev)
    e0 = ev[0]
    assert e0["md5"] and e0["sha256"]
    assert e0["stage"] in ("acquired", "verified")


def test_db_unmodified_after_run(make_activity_db, tmp_path):
    from engine.integrity import hash_file

    gt = make_activity_db(n_insert=20, m_delete=5)
    before = hash_file(gt["db_path"])
    args = build_parser().parse_args([gt["db_path"], "--ui", "-o", str(tmp_path / "r.json")])
    run(args)
    after = hash_file(gt["db_path"])
    assert before == after  # read-only proven by hash equality
