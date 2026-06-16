import hashlib
import json

from engine.cli import build_parser, run


def _run(db, out):
    args = build_parser().parse_args(
        [db, "--ui", "-o", str(out), "--analyzed-at", "2026-06-15T00:00:00Z"]
    )
    return run(args)


def test_same_input_same_output(make_activity_db, tmp_path):
    gt = make_activity_db(n_insert=40, m_delete=12)
    a = _run(gt["db_path"], tmp_path / "a.json")
    b = _run(gt["db_path"], tmp_path / "b.json")

    # With analyzed_at fixed, records + stats must be byte-identical run to run.
    def norm(d):
        return json.dumps(
            {"stats": d["meta"]["stats"], "activities": d["activities"]},
            sort_keys=True,
            ensure_ascii=False,
        )

    assert (
        hashlib.sha256(norm(a).encode()).hexdigest()
        == hashlib.sha256(norm(b).encode()).hexdigest()
    )
