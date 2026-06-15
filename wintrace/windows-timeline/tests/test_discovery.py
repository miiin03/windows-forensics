"""Tests for ActivitiesCache.db discovery and discovery-driven CLI behavior."""

import json
import subprocess
import sys
from pathlib import Path

from engine.discovery import ActivityDbCandidate, find_activitiescache_dbs


ROOT = Path(__file__).resolve().parents[1]


def _cdp_db(root: Path, account: str, with_wal=False, with_shm=False) -> Path:
    db = root / "ConnectedDevicesPlatform" / account / "ActivitiesCache.db"
    db.parent.mkdir(parents=True)
    db.write_bytes(b"placeholder")
    if with_wal:
        db.with_name(db.name + "-wal").write_bytes(b"wal")
    if with_shm:
        db.with_name(db.name + "-shm").write_bytes(b"shm")
    return db


def test_find_activitiescache_dbs_scans_all_account_folders(tmp_path):
    first = _cdp_db(tmp_path, "account-a", with_wal=True)
    second = _cdp_db(tmp_path, "account-b", with_shm=True)

    found = find_activitiescache_dbs(root=tmp_path)

    assert found == [
        ActivityDbCandidate(
            db_path=str(first),
            wal_path=str(first) + "-wal",
            shm_path=None,
            account="account-a",
        ),
        ActivityDbCandidate(
            db_path=str(second),
            wal_path=None,
            shm_path=str(second) + "-shm",
            account="account-b",
        ),
    ]


def test_find_activitiescache_dbs_uses_wt_cdp_dir_when_root_omitted(tmp_path, monkeypatch):
    db = _cdp_db(tmp_path, "env-account")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setenv("WT_CDP_DIR", str(tmp_path / "ConnectedDevicesPlatform"))

    found = find_activitiescache_dbs()

    assert [item.db_path for item in found] == [str(db)]


def test_cli_discovers_multiple_dbs_and_tags_records(make_activity_db, tmp_path):
    root = tmp_path / "LocalAppData"
    first_dir = root / "ConnectedDevicesPlatform" / "account-a"
    second_dir = root / "ConnectedDevicesPlatform" / "account-b"
    first_dir.mkdir(parents=True)
    second_dir.mkdir(parents=True)
    first = make_activity_db(name=str(first_dir / "ActivitiesCache.db"), n_insert=2, m_delete=0)
    second = make_activity_db(name=str(second_dir / "ActivitiesCache.db"), n_insert=3, m_delete=0)
    out = tmp_path / "result.json"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "engine",
            "--root",
            str(root),
            "--source",
            "live",
            "-o",
            str(out),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    obj = json.loads(out.read_text(encoding="utf-8"))
    assert [f["account"] for f in obj["source_files"]] == ["account-a", "account-b"]
    assert obj["stats"]["live"] == 5
    assert {r["source_db_account"] for r in obj["records"]} == {"account-a", "account-b"}
    assert {r["source_db_path"] for r in obj["records"]} == {
        first["db_path"],
        second["db_path"],
    }


def test_cli_stats_only_without_output_writes_stdout(make_activity_db, tmp_path):
    root = tmp_path / "LocalAppData"
    db_dir = root / "ConnectedDevicesPlatform" / "account-a"
    db_dir.mkdir(parents=True)
    make_activity_db(name=str(db_dir / "ActivitiesCache.db"), n_insert=1, m_delete=0)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "engine",
            "--root",
            str(root),
            "--source",
            "live",
            "--stats-only",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    obj = json.loads(result.stdout)
    assert "records" not in obj
    assert obj["stats"]["live"] == 1


def test_cli_no_discovered_dbs_prints_friendly_message(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "engine", "--root", str(tmp_path), "--stats-only"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    assert "No ActivitiesCache.db files found" in result.stderr


def test_gitignore_blocks_generated_and_private_database_artifacts():
    patterns = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    for expected in (
        "__pycache__/",
        "*.pyc",
        "/out",
        "result.json",
        "*.db",
        "*.db-wal",
        "*.db-shm",
    ):
        assert expected in patterns
