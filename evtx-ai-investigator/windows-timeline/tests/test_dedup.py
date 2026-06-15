"""Tests for GUID-based live/carved de-duplication."""

from engine.dedup import deduplicate


def _record(guid, source, confidence=1.0, etag=1, app="app.exe"):
    return {
        "table": "Activity",
        "Id": guid,
        "AppId_raw": app,
        "source": source,
        "sources": [source],
        "confidence": confidence,
        "is_deleted": source != "live",
        "is_prior_version": False,
        "other_columns": {"ETag": etag},
    }


def test_identical_carved_record_matching_live_guid_is_dropped():
    live = [_record("a" * 32, "live", etag=4)]
    carved = [_record("a" * 32, "freelist", confidence=0.85, etag=4)]

    assert deduplicate(live, carved) == live


def test_changed_carved_record_matching_live_guid_is_kept_as_prior_version():
    live = [_record("b" * 32, "live", etag=5)]
    carved = [_record("b" * 32, "freelist", confidence=0.85, etag=4)]

    merged = deduplicate(live, carved)

    assert len(merged) == 2
    prior = merged[1]
    assert prior["is_prior_version"] is True
    assert prior["is_deleted"] is False
    assert prior["source"] == "freelist"


def test_carved_records_with_same_guid_merge_to_best_source_and_all_sources():
    low = _record("c" * 32, "freeblock", confidence=0.55, etag=7)
    high = _record("c" * 32, "freelist", confidence=0.85, etag=7)

    merged = deduplicate([], [low, high])

    assert len(merged) == 1
    assert merged[0]["source"] == "freelist"
    assert merged[0]["sources"] == ["freeblock", "freelist"]
    assert merged[0]["confidence"] == 0.85
    assert merged[0]["is_deleted"] is True


def test_carved_records_tie_break_on_non_null_content_count():
    sparse = _record("d" * 32, "freelist", confidence=0.7, etag=None)
    full = _record("d" * 32, "freelist_brute", confidence=0.7, etag=9)

    merged = deduplicate([], [sparse, full])

    assert len(merged) == 1
    assert merged[0]["source"] == "freelist_brute"
    assert merged[0]["sources"] == ["freelist", "freelist_brute"]
    assert merged[0]["other_columns"]["ETag"] == 9


def test_keyless_fragments_are_not_merged():
    first = _record(None, "freeblock", confidence=0.4, etag=1)
    second = _record(None, "freeblock", confidence=0.5, etag=1)

    merged = deduplicate([], [first, second])

    assert merged == [first, second]
