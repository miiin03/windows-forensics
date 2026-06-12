"""Tests for JSON envelope export and CLI smoke behavior."""

import json
import subprocess
import sys
from pathlib import Path

from engine.export import build_output, write_json


ROOT = Path(__file__).resolve().parents[1]


def _record(source, deleted=False, prior=False):
    return {
        "table": "Activity",
        "Id": source * 32 if len(source) == 1 else source,
        "source": source,
        "sources": [source],
        "is_deleted": deleted,
        "is_prior_version": prior,
        "confidence": 1.0 if source == "live" else 0.85,
        "payload_truncated": False,
    }


def test_build_output_wraps_records_with_source_file_and_stats():
    live = [_record("live")]
    carved = [_record("freelist", deleted=True), _record("freeblock", prior=True)]
    info = {
        "path": "/tmp/ActivitiesCache.db",
        "page_size": 4096,
        "freelist_count": 12,
        "wal_present": False,
    }

    obj = build_output(live, carved, info)

    assert obj["schema_version"] == 1
    assert obj["tool"] == "windows-timeline"
    assert obj["source_file"]["path"] == "/tmp/ActivitiesCache.db"
    assert obj["source_file"]["page_size"] == 4096
    assert obj["stats"] == {
        "live": 1,
        "carved_total": 2,
        "by_source": {"freeblock": 1, "freelist": 1, "live": 1},
        "deleted_recovered": 1,
        "prior_versions": 1,
    }
    assert obj["records"] == live + carved


def test_write_json_supports_pretty_output(tmp_path):
    out = tmp_path / "result.json"
    obj = build_output([], [], {"path": "x", "page_size": 4096, "freelist_count": 0})

    write_json(out, obj, pretty=True)

    text = out.read_text(encoding="utf-8")
    assert "\n  " in text
    assert json.loads(text)["source_file"]["path"] == "x"


def test_cli_help_smoke():
    result = subprocess.run(
        [sys.executable, "-m", "engine", "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    assert "ActivitiesCache.db" in result.stdout
    assert "-o" in result.stdout


def test_cli_writes_json_for_synthetic_db(make_activity_db, tmp_path):
    gt = make_activity_db(n_insert=12, m_delete=0)
    out = tmp_path / "timeline.json"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "engine",
            gt["db_path"],
            "-o",
            str(out),
            "--source",
            "live",
            "--pretty",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    obj = json.loads(out.read_text(encoding="utf-8"))
    assert obj["source_file"]["path"] == gt["db_path"]
    assert obj["stats"]["live"] == 12
    assert obj["stats"]["carved_total"] == 0
    assert len(obj["records"]) == 12
