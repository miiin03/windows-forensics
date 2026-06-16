import hashlib

from engine.integrity import hash_file, custody_record


def test_hash_file_md5_sha256(tmp_path):
    p = tmp_path / "evidence.bin"
    data = b"ActivitiesCache sample bytes"
    p.write_bytes(data)
    h = hash_file(str(p))
    assert h["md5"] == hashlib.md5(data).hexdigest()
    assert h["sha256"] == hashlib.sha256(data).hexdigest()
    assert h["size"] == len(data)


def test_hash_file_missing_returns_none(tmp_path):
    assert hash_file(str(tmp_path / "nope.db")) is None


def test_custody_record_shape(tmp_path):
    p = tmp_path / "ActivitiesCache.db"
    p.write_bytes(b"x" * 10)
    rec = custody_record(str(p), stage="acquired")
    assert rec["path"].endswith("ActivitiesCache.db")
    assert rec["stage"] == "acquired"
    assert rec["md5"] and rec["sha256"] and rec["size"] == 10
