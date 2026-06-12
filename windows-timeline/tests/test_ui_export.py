"""TDD for engine.ui_export.build_ui_output (Stage 8 — UI export mode)."""

from __future__ import annotations

import json
import os

import pytest

from engine.ui_export import build_ui_output


# ── Synthetic record builders ─────────────────────────────────────────────────

def _live(
    *,
    guid: str = "aabbccddeeff00112233445566778899",
    appid_raw: str = '[{"platform":"windows_win32","application":"C:\\\\Windows\\\\System32\\\\cmd.exe"}]',
    app_name: str = "Command Prompt",
    activity_type: int = 5,
    start_iso: str = "2024-06-11T12:00:00Z",
    end_iso: str = "2024-06-11T12:10:00Z",
    lmt_iso: str = "2024-06-11T12:10:00Z",
    display_text: str = "test activity",
) -> dict:
    return {
        "source": "live",
        "is_deleted": False,
        "confidence_label": "high",
        "Id": guid,
        "AppId_raw": appid_raw,
        "app_name": app_name,
        "ActivityType": activity_type,
        "timestamps": {
            "StartTime": {"epoch": 1718107200, "iso8601": start_iso},
            "EndTime": {"epoch": 1718107800, "iso8601": end_iso},
            "LastModifiedTime": {"epoch": 1718107800, "iso8601": lmt_iso},
        },
        "Payload": {
            "parsed": {"displayText": display_text, "activeDurationSeconds": 60},
            "parse_ok": True,
            "raw_len": 80,
        },
        "ClipboardPayload": {"parsed": None, "parse_ok": False, "raw_len": 0},
        "provenance": {"rowid": 1},
    }


def _carved(
    *,
    guid: str = "112233445566778899aabbccddee0011",
    source: str = "freelist",
    confidence_label: str = "medium",
    page_no: int = 5,
    cell_offset: int = 1234,
    display_text: str = "carved activity",
) -> dict:
    return {
        "source": source,
        "is_deleted": True,
        "confidence_label": confidence_label,
        "Id": guid,
        "AppId_raw": '[{"platform":"windows_win32","application":"C:\\\\Program Files\\\\app.exe"}]',
        "app_name": "App",
        "ActivityType": 5,
        "timestamps": {
            "StartTime": {"epoch": 1718200000, "iso8601": "2024-06-12T16:26:40Z"},
            "LastModifiedTime": {"epoch": 1718200000, "iso8601": "2024-06-12T16:26:40Z"},
        },
        "Payload": {
            "parsed": {"displayText": display_text},
            "parse_ok": True,
            "raw_len": 60,
        },
        "ClipboardPayload": {"parsed": None, "parse_ok": False, "raw_len": 0},
        "provenance": {
            "page_no": page_no,
            "cell_offset": cell_offset,
            "rowid": None,
            "byte_range": [page_no * 4096, page_no * 4096 + 300],
            "serial_types": [44] * 31,
            "decode_errors": [],
        },
    }


# ── Top-level schema ──────────────────────────────────────────────────────────

def test_top_level_keys_present():
    result = build_ui_output([], [])
    assert "meta" in result
    assert "activities" in result
    assert isinstance(result["activities"], list)


def test_meta_required_fields():
    result = build_ui_output([], [{"path": "/test.db"}], analyzed_at="2026-06-12T01:00:00Z")
    meta = result["meta"]
    assert meta["tool"] == "WinActivityForensics"
    assert meta["version"] == "0.3"
    assert meta["timezone"] == "Asia/Seoul (UTC+9)"
    assert "analyzed_at_kst" in meta
    assert "stats" in meta
    assert "sources" in meta


def test_meta_analyzed_at_kst_conversion():
    result = build_ui_output([], [], analyzed_at="2026-06-12T01:00:00Z")
    # UTC 01:00 → KST 10:00 (+09:00)
    assert result["meta"]["analyzed_at_kst"] == "2026-06-12T10:00:00+09:00"


def test_meta_sources_has_path():
    result = build_ui_output([], [{"path": "/some/path/ActivitiesCache.db"}])
    assert result["meta"]["sources"][0]["path"] == "/some/path/ActivitiesCache.db"
    assert result["meta"]["sources"][0]["artifact"] == "timeline"


def test_meta_sources_empty_when_no_source_files():
    # Single dummy entry for empty source_files=[]
    result = build_ui_output([], [])
    assert len(result["meta"]["sources"]) == 1


# ── Stats ─────────────────────────────────────────────────────────────────────

def test_stats_empty():
    result = build_ui_output([], [])
    s = result["meta"]["stats"]
    assert s["total"] == 0
    assert s["normal"] == 0
    assert s["carved"] == 0
    assert s["encrypted_skipped"] == 0
    assert s["decrypted_ok"] == 0
    assert s["by_artifact"]["timeline"] == 0


def test_stats_counts_correctly():
    recs = [_live(), _carved(), _carved(guid="ff" * 16, source="freeblock")]
    result = build_ui_output(recs, [])
    s = result["meta"]["stats"]
    assert s["total"] == 3
    assert s["normal"] == 1
    assert s["carved"] == 2
    assert s["by_artifact"]["timeline"] == 3


# ── Activity field requirements ───────────────────────────────────────────────

_REQUIRED_FIELDS = {
    "id", "artifact", "category", "source", "source_browser", "payload_format",
    "confidence", "decrypted", "app_id", "app_name", "title", "url", "detail",
    "secret_value", "start_time_kst", "end_time_kst", "last_modified_kst",
    "raw_payload_b64",
}


def test_activity_has_all_required_fields():
    result = build_ui_output([_live()], [])
    act = result["activities"][0]
    missing = _REQUIRED_FIELDS - set(act.keys())
    assert not missing, f"Missing fields: {missing}"


def test_null_fixed_fields():
    result = build_ui_output([_live()], [])
    act = result["activities"][0]
    assert act["source_browser"] is None
    assert act["decrypted"] is None
    assert act["secret_value"] is None
    assert act["raw_payload_b64"] is None
    assert act["artifact"] == "timeline"


# ── source / payload_format / confidence ─────────────────────────────────────

def test_live_source_is_normal():
    result = build_ui_output([_live()], [])
    assert result["activities"][0]["source"] == "normal"


def test_carved_source_is_carved():
    result = build_ui_output([_carved()], [])
    assert result["activities"][0]["source"] == "carved"


def test_live_payload_format_json():
    result = build_ui_output([_live()], [])
    assert result["activities"][0]["payload_format"] == "json"


def test_freelist_payload_format_sqlite_cell():
    result = build_ui_output([_carved(source="freelist")], [])
    assert result["activities"][0]["payload_format"] == "sqlite_cell"


def test_freeblock_payload_format_sqlite_cell():
    result = build_ui_output([_carved(source="freeblock")], [])
    assert result["activities"][0]["payload_format"] == "sqlite_cell"


def test_slack_payload_format_sqlite_cell():
    result = build_ui_output([_carved(source="slack")], [])
    assert result["activities"][0]["payload_format"] == "sqlite_cell"


def test_wal_payload_format_wal_frame():
    result = build_ui_output([_carved(source="wal")], [])
    assert result["activities"][0]["payload_format"] == "wal_frame"


def test_wal_stale_payload_format_wal_frame():
    result = build_ui_output([_carved(source="wal_stale")], [])
    assert result["activities"][0]["payload_format"] == "wal_frame"


def test_live_confidence_high():
    rec = _live()
    result = build_ui_output([rec], [])
    assert result["activities"][0]["confidence"] == "high"


def test_carved_confidence_from_label():
    rec = _carved(confidence_label="low")
    result = build_ui_output([rec], [])
    assert result["activities"][0]["confidence"] == "low"


# ── KST timestamps ────────────────────────────────────────────────────────────

def test_start_time_utc_to_kst():
    rec = _live(start_iso="2024-06-11T12:00:00Z")
    result = build_ui_output([rec], [])
    # UTC 12:00 + 9h = KST 21:00
    assert result["activities"][0]["start_time_kst"] == "2024-06-11T21:00:00+09:00"


def test_end_time_utc_to_kst():
    rec = _live(end_iso="2024-06-11T12:10:00Z")
    result = build_ui_output([rec], [])
    assert result["activities"][0]["end_time_kst"] == "2024-06-11T21:10:00+09:00"


def test_last_modified_utc_to_kst():
    rec = _live(lmt_iso="2024-06-11T00:00:00Z")
    result = build_ui_output([rec], [])
    assert result["activities"][0]["last_modified_kst"] == "2024-06-11T09:00:00+09:00"


def test_kst_timestamp_ends_with_offset():
    rec = _live(start_iso="2024-01-01T15:30:00Z")
    result = build_ui_output([rec], [])
    ts = result["activities"][0]["start_time_kst"]
    assert ts is not None
    assert ts.endswith("+09:00")


def test_null_timestamp_stays_null():
    rec = _live()
    rec["timestamps"].pop("EndTime", None)
    result = build_ui_output([rec], [])
    assert result["activities"][0]["end_time_kst"] is None


# ── id ────────────────────────────────────────────────────────────────────────

def test_id_from_guid():
    rec = _live(guid="0102030405060708090a0b0c0d0e0f10")
    result = build_ui_output([rec], [])
    assert result["activities"][0]["id"] == "0102030405060708090a0b0c0d0e0f10"


def test_id_synthesis_page_offset():
    rec = _carved(page_no=42, cell_offset=123)
    rec["Id"] = None
    result = build_ui_output([rec], [])
    assert result["activities"][0]["id"] == "page-42-off123"


def test_id_synthesis_rowid_for_live_no_guid():
    rec = _live()
    rec["Id"] = None
    rec["provenance"] = {"rowid": 7}
    result = build_ui_output([rec], [])
    assert result["activities"][0]["id"] == "live-rowid-7"


# ── category ─────────────────────────────────────────────────────────────────

def test_category_app_exec_type_5():
    rec = _live()
    rec["ActivityType"] = 5
    assert build_ui_output([rec], [])["activities"][0]["category"] == "app_exec"


def test_category_app_exec_type_6():
    rec = _live()
    rec["ActivityType"] = 6
    assert build_ui_output([rec], [])["activities"][0]["category"] == "app_exec"


def test_category_file_open_from_uri():
    rec = _live()
    rec["Payload"]["parsed"] = {"uri": "file:///C:/Users/test/doc.txt"}
    assert build_ui_output([rec], [])["activities"][0]["category"] == "file_open"


def test_category_web_visit_http():
    rec = _live()
    rec["Payload"]["parsed"] = {"url": "https://example.com/search?q=test"}
    assert build_ui_output([rec], [])["activities"][0]["category"] == "web_visit"


def test_category_web_visit_http_plain():
    rec = _live()
    rec["Payload"]["parsed"] = {"url": "http://internal.example.com"}
    assert build_ui_output([rec], [])["activities"][0]["category"] == "web_visit"


def test_category_file_open_clipboard():
    rec = _live()
    rec["ClipboardPayload"]["parsed"] = {"content": "some text"}
    assert build_ui_output([rec], [])["activities"][0]["category"] == "file_open"


# ── title / url ───────────────────────────────────────────────────────────────

def test_title_from_display_text():
    rec = _live(display_text="보고서.docx")
    assert build_ui_output([rec], [])["activities"][0]["title"] == "보고서.docx"


def test_title_none_when_no_payload_text():
    rec = _live()
    rec["Payload"] = {"parsed": None, "parse_ok": False, "raw_len": 0}
    assert build_ui_output([rec], [])["activities"][0]["title"] is None


def test_url_from_file_uri():
    rec = _live()
    rec["Payload"]["parsed"] = {"uri": "file:///C:/test.txt", "displayText": "test"}
    url = build_ui_output([rec], [])["activities"][0]["url"]
    assert url is not None
    assert url.startswith("file:///")


def test_url_from_http():
    rec = _live()
    rec["Payload"]["parsed"] = {"url": "https://example.com/page"}
    url = build_ui_output([rec], [])["activities"][0]["url"]
    assert url is not None
    assert url.startswith("https://")


def test_url_none_when_no_uri():
    rec = _live(display_text="activity without url")
    assert build_ui_output([rec], [])["activities"][0]["url"] is None


# ── app_id / app_name ─────────────────────────────────────────────────────────

def test_appid_win32_known_exe():
    rec = _live(appid_raw='[{"platform":"windows_win32","application":"C:\\\\Windows\\\\NOTEPAD.EXE"}]')
    act = build_ui_output([rec], [])["activities"][0]
    assert act["app_id"] == "NOTEPAD.EXE"
    assert act["app_name"] == "Notepad"


def test_appid_win32_unknown_exe():
    rec = _live(appid_raw='[{"platform":"windows_win32","application":"C:\\\\Tools\\\\mytool.exe"}]')
    act = build_ui_output([rec], [])["activities"][0]
    assert act["app_id"] == "MYTOOL.EXE"
    assert act["app_name"] is not None


def test_appid_package_id():
    rec = _live(
        appid_raw='[{"platform":"windows_packageid","application":"Microsoft.WindowsCalculator_8wekyb3d8bbwe"}]'
    )
    act = build_ui_output([rec], [])["activities"][0]
    assert act["app_id"] == "Microsoft.WindowsCalculator_8wekyb3d8bbwe"
    # name should contain "Calculator" or similar human-readable form
    assert act["app_name"] is not None
    assert len(act["app_name"]) > 0


def test_appid_none_falls_back_to_app_name():
    rec = _live(appid_raw=None, app_name="FallbackApp")
    act = build_ui_output([rec], [])["activities"][0]
    assert act["app_name"] == "FallbackApp"


# ── detail ────────────────────────────────────────────────────────────────────

def test_detail_live_is_none():
    assert build_ui_output([_live()], [])["activities"][0]["detail"] is None


def test_detail_freelist_has_provenance():
    result = build_ui_output([_carved(source="freelist", page_no=472, cell_offset=3372)], [])
    detail = result["activities"][0]["detail"]
    assert detail is not None
    assert "freelist" in detail
    assert "p472" in detail
    assert "off3372" in detail


def test_detail_freeblock_has_provenance():
    result = build_ui_output([_carved(source="freeblock", page_no=3)], [])
    detail = result["activities"][0]["detail"]
    assert "freeblock" in detail


def test_detail_wal_message():
    detail = build_ui_output([_carved(source="wal")], [])["activities"][0]["detail"]
    assert "WAL" in detail
    assert "구버전" in detail


def test_detail_wal_stale_message():
    detail = build_ui_output([_carved(source="wal_stale")], [])["activities"][0]["detail"]
    assert "WAL" in detail
    assert "stale" in detail


def test_detail_slack_has_provenance():
    detail = build_ui_output([_carved(source="slack", page_no=7, cell_offset=99)], [])["activities"][0]["detail"]
    assert "slack" in detail
    assert "p7" in detail


# ── End-to-end with full pipeline ─────────────────────────────────────────────

def test_full_pipeline_schema(make_activity_db):
    """Round-trip: build DB → live parse + freelist carve → build_ui_output → validate schema."""
    from engine.carver.freelist import carve_freelist
    from engine.dedup import deduplicate
    from engine.live_parser import read_activity
    from engine.normalize import normalize_records
    from engine.pages import PageSource

    gt = make_activity_db(n_insert=30, m_delete=15)
    ps = PageSource.from_file(gt["db_path"])
    live = normalize_records(read_activity(gt["db_path"], immutable=True))
    carved = normalize_records(carve_freelist(ps))
    all_records = deduplicate(live, carved)

    result = build_ui_output(
        all_records,
        [{"path": gt["db_path"]}],
        analyzed_at="2026-06-12T00:00:00Z",
    )

    assert result["meta"]["tool"] == "WinActivityForensics"
    assert isinstance(result["activities"], list)
    assert len(result["activities"]) > 0

    for act in result["activities"]:
        missing = _REQUIRED_FIELDS - set(act.keys())
        assert not missing, f"Missing fields in activity: {missing}"
        assert act["artifact"] == "timeline"
        assert act["source"] in ("normal", "carved")
        assert act["payload_format"] in ("json", "sqlite_cell", "wal_frame")
        assert act["confidence"] in ("high", "medium", "low", "very_low")
        assert act["source_browser"] is None
        assert act["decrypted"] is None
        assert act["secret_value"] is None
        assert act["id"]  # non-empty

    s = result["meta"]["stats"]
    assert s["total"] == len(result["activities"])
    assert s["normal"] + s["carved"] == s["total"]


# ── Sample file generation ────────────────────────────────────────────────────

_SAMPLE_RECORDS = [
    # Live records
    _live(
        guid="00112233445566778899aabbccddeeff",
        appid_raw='[{"platform":"windows_win32","application":"C:\\\\Program Files\\\\Microsoft Office\\\\root\\\\Office16\\\\WINWORD.EXE"}]',
        app_name="Microsoft Word",
        activity_type=5,
        start_iso="2026-06-12T00:00:00Z",
        end_iso="2026-06-12T01:00:00Z",
        lmt_iso="2026-06-12T01:00:00Z",
        display_text="보고서_2026Q2.docx",
    ),
    _live(
        guid="ffeeddccbbaa99887766554433221100",
        appid_raw='[{"platform":"windows_win32","application":"C:\\\\Program Files (x86)\\\\Google\\\\Chrome\\\\Application\\\\CHROME.EXE"}]',
        app_name="Google Chrome",
        activity_type=5,
        start_iso="2026-06-12T02:00:00Z",
        end_iso="2026-06-12T02:30:00Z",
        lmt_iso="2026-06-12T02:30:00Z",
        display_text="GitHub - anthropics/claude-code",
    ),
    _live(
        guid="aabbccddeeff00112233445566778899",
        appid_raw='[{"platform":"windows_win32","application":"C:\\\\Windows\\\\explorer.exe"}]',
        app_name="Windows Explorer",
        activity_type=5,
        start_iso="2026-06-12T03:00:00Z",
        end_iso="2026-06-12T03:05:00Z",
        lmt_iso="2026-06-12T03:05:00Z",
        display_text="C:\\\\Users\\\\user\\\\Documents",
    ),
    # Carved records
    _carved(
        guid="11223344556677889900aabbccddeeff",
        source="freelist",
        confidence_label="medium",
        page_no=12,
        cell_offset=488,
        display_text="삭제된_파일.xlsx",
    ),
    _carved(
        guid="99887766554433221100ffeeddccbbaa",
        source="wal",
        confidence_label="medium",
        page_no=7,
        cell_offset=200,
        display_text="수정 전 활동 (WAL 복구)",
    ),
    _carved(
        guid="aabb99887766ccdd00112233ffeedd55",
        source="freeblock",
        confidence_label="low",
        page_no=5,
        cell_offset=3372,
        display_text="freeblock 복구 항목",
    ),
]
# Inject web_visit URL into the Chrome record
_SAMPLE_RECORDS[1]["Payload"]["parsed"]["url"] = "https://github.com/anthropics/claude-code"
# Inject file URI into the Explorer record
_SAMPLE_RECORDS[2]["Payload"]["parsed"]["uri"] = "file:///C:/Users/user/Documents"


def test_sample_file_written_and_valid(tmp_path):
    """Generate sample/timeline_result.sample.json — committed to repo as demo data."""
    result = build_ui_output(
        _SAMPLE_RECORDS,
        [{"path": "sample/ActivitiesCache.db (synthetic)"}],
        analyzed_at="2026-06-12T10:46:00Z",  # fixed for reproducibility
    )

    # Validate schema
    assert result["meta"]["tool"] == "WinActivityForensics"
    assert len(result["activities"]) == len(_SAMPLE_RECORDS)
    for act in result["activities"]:
        missing = _REQUIRED_FIELDS - set(act.keys())
        assert not missing, f"Missing fields: {missing}"

    # Write to the canonical sample path (repo artifact)
    sample_dir = os.path.join(
        os.path.dirname(__file__), "..", "sample"
    )
    os.makedirs(sample_dir, exist_ok=True)
    sample_path = os.path.join(sample_dir, "timeline_result.sample.json")
    with open(sample_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write("\n")


# ── Bug-fix regression: source labeling (Bug 1) ───────────────────────────────

def _wal_prior_not_deleted() -> dict:
    """WAL prior-version record: source='wal' but is_deleted=False (still in live DB as modified)."""
    rec = _carved(source="wal", confidence_label="medium")
    rec["is_deleted"] = False  # WAL prior version — modified, not deleted
    return rec


def test_wal_prior_version_is_deleted_false_maps_to_carved():
    """Bug 1: WAL record with is_deleted=False must still be 'carved', not 'normal'."""
    result = build_ui_output([_wal_prior_not_deleted()], [])
    assert result["activities"][0]["source"] == "carved"


def test_freelist_is_deleted_false_maps_to_carved():
    """Bug 1: freelist record with is_deleted=False must still be 'carved'."""
    rec = _carved(source="freelist")
    rec["is_deleted"] = False
    result = build_ui_output([rec], [])
    assert result["activities"][0]["source"] == "carved"


def test_freeblock_is_deleted_false_maps_to_carved():
    """Bug 1: freeblock with is_deleted=False must be 'carved'."""
    rec = _carved(source="freeblock")
    rec["is_deleted"] = False
    result = build_ui_output([rec], [])
    assert result["activities"][0]["source"] == "carved"


def test_slack_is_deleted_false_maps_to_carved():
    """Bug 1: slack with is_deleted=False must be 'carved'."""
    rec = _carved(source="slack")
    rec["is_deleted"] = False
    result = build_ui_output([rec], [])
    assert result["activities"][0]["source"] == "carved"


def test_stats_source_based_not_is_deleted():
    """Bug 1: stats.normal counts internal source=='live', not is_deleted==False."""
    live_rec = _live()  # source='live', is_deleted=False → normal
    wal_not_del = _wal_prior_not_deleted()  # source='wal', is_deleted=False → carved
    carved_del = _carved()  # source='freelist', is_deleted=True → carved

    result = build_ui_output([live_rec, wal_not_del, carved_del], [],
                              analyzed_at="2026-06-12T00:00:00Z")
    s = result["meta"]["stats"]
    assert s["normal"] == 1   # only the live_rec
    assert s["carved"] == 2   # wal + freelist
    assert s["total"] == 3


def test_live_source_always_normal_regardless_of_is_deleted():
    """Bug 1: live record (source='live') is always 'normal'."""
    rec = _live()
    rec["is_deleted"] = True  # unusual but edge-case safe
    result = build_ui_output([rec], [])
    assert result["activities"][0]["source"] == "normal"


# ── Bug-fix regression: garbage app_name (Bug 2, revised) ────────────────────
# Policy: strip control chars (0x00-0x1F, 0x7F) only; keep U+FFFD so
# partially-recovered forensic text stays visible in the viewer.

def test_appid_control_chars_stripped_fffd_kept():
    """Control chars stripped; U+FFFD kept; readable text not silently discarded."""
    garbage_appid = json.dumps([{
        "platform": "windows_win32",
        "application": "Microsoft�Device\x00Broken\x1f",
    }])
    rec = _live(appid_raw=garbage_appid)
    act = build_ui_output([rec], [])["activities"][0]
    assert "\x00" not in (act["app_name"] or "")
    assert "\x1f" not in (act["app_name"] or "")
    assert act["app_name"] != "(복구 단편)"
    combined = (act["app_name"] or "") + (act["app_id"] or "")
    assert "MICROSOFT" in combined.upper()


def test_appid_replacement_char_in_raw_string_preserved():
    """U+FFFD in non-JSON AppId kept as forensic marker; \x00 stripped."""
    rec = _live(appid_raw="MicrosoftEdge�\x00garbage")
    act = build_ui_output([rec], [])["activities"][0]
    assert act["app_name"] is not None
    assert "\x00" not in act["app_name"]
    assert "�" in act["app_name"]  # preserved for forensic visibility
    assert act["app_name"] != "(복구 단편)"


def test_appid_control_char_in_path_stripped():
    """\x01 in exe path stripped; clean remainder used as app_id/app_name."""
    garbage_appid = json.dumps([{
        "platform": "windows_win32",
        "application": "C:\\Windows\\\x01evil.exe",
    }])
    rec = _live(appid_raw=garbage_appid)
    act = build_ui_output([rec], [])["activities"][0]
    assert "\x01" not in (act["app_id"] or "")
    assert "\x01" not in (act["app_name"] or "")
    assert act["app_id"] is not None or act["app_name"] is not None


def test_appid_clean_string_unaffected():
    """Clean AppId produces correct app_id/app_name with no fallback."""
    rec = _live(appid_raw='[{"platform":"windows_win32","application":"C:\\\\Windows\\\\NOTEPAD.EXE"}]')
    act = build_ui_output([rec], [])["activities"][0]
    assert act["app_id"] == "NOTEPAD.EXE"
    assert act["app_name"] == "Notepad"


def test_title_control_chars_stripped_fffd_kept():
    """Control chars stripped from title; U+FFFD kept for forensic visibility."""
    rec = _live()
    rec["Payload"]["parsed"] = {"displayText": "clean\x00text�more"}
    act = build_ui_output([rec], [])["activities"][0]
    title = act["title"]
    assert title is not None
    assert "\x00" not in title
    assert "�" in title  # preserved


# ── Bug-fix regression: timestamp range (Bug 3) ───────────────────────────────

def test_timestamp_epoch_zero_is_null():
    """Bug 3: EndTime epoch 0 → ISO 1970-01-01T00:00:00Z → end_time_kst=None."""
    rec = _live()
    rec["timestamps"]["EndTime"] = {"epoch": 0, "iso8601": "1970-01-01T00:00:00Z"}
    result = build_ui_output([rec], [], analyzed_at="2026-06-12T00:00:00Z")
    assert result["activities"][0]["end_time_kst"] is None


def test_timestamp_year_1907_is_null():
    """Bug 3: pre-2010 year in carved timestamp → null."""
    rec = _carved()
    rec["timestamps"]["StartTime"] = {"epoch": -2000000000, "iso8601": "1906-08-02T16:26:40Z"}
    result = build_ui_output([rec], [], analyzed_at="2026-06-12T00:00:00Z")
    assert result["activities"][0]["start_time_kst"] is None


def test_timestamp_year_2030_far_future_is_null():
    """Bug 3: year beyond analyzed_at+1 → null."""
    rec = _live()
    rec["timestamps"]["StartTime"] = {"epoch": 9999999999, "iso8601": "2286-11-20T17:46:39Z"}
    result = build_ui_output([rec], [], analyzed_at="2026-06-12T00:00:00Z")
    # analyzed_at year=2026 → year_max=2027; 2286 > 2027 → None
    assert result["activities"][0]["start_time_kst"] is None


def test_timestamp_valid_2024_not_null():
    """Bug 3: valid 2024 timestamp passes through."""
    rec = _live(start_iso="2024-06-11T12:00:00Z")
    result = build_ui_output([rec], [], analyzed_at="2026-06-12T00:00:00Z")
    assert result["activities"][0]["start_time_kst"] is not None
    assert "2024" in result["activities"][0]["start_time_kst"]


def test_no_1970_in_end_time_kst(make_activity_db):
    """Bug 3: full pipeline output must not contain any 1970 end_time_kst."""
    from engine.carver.freelist import carve_freelist
    from engine.dedup import deduplicate
    from engine.live_parser import read_activity
    from engine.normalize import normalize_records
    from engine.pages import PageSource

    gt = make_activity_db(n_insert=30, m_delete=10)
    ps = PageSource.from_file(gt["db_path"])
    live = normalize_records(read_activity(gt["db_path"], immutable=True))
    carved = normalize_records(carve_freelist(ps))
    all_records = deduplicate(live, carved)

    result = build_ui_output(all_records, [{"path": gt["db_path"]}],
                              analyzed_at="2026-06-12T00:00:00Z")
    for act in result["activities"]:
        ts = act.get("end_time_kst")
        assert ts is None or "1970" not in ts, f"1970 in end_time_kst: {ts}"


def test_no_garbage_app_name_in_pipeline(make_activity_db):
    """Bug 2: full pipeline app_name/app_id must not contain control chars (U+FFFD is OK)."""
    import re as _re
    control_re = _re.compile(r"[\x00-\x1f\x7f]")

    from engine.carver.freelist import carve_freelist
    from engine.dedup import deduplicate
    from engine.live_parser import read_activity
    from engine.normalize import normalize_records
    from engine.pages import PageSource

    gt = make_activity_db(n_insert=30, m_delete=15)
    ps = PageSource.from_file(gt["db_path"])
    live = normalize_records(read_activity(gt["db_path"], immutable=True))
    carved = normalize_records(carve_freelist(ps))
    all_records = deduplicate(live, carved)

    result = build_ui_output(all_records, [{"path": gt["db_path"]}],
                              analyzed_at="2026-06-12T00:00:00Z")
    for act in result["activities"]:
        name = act.get("app_name") or ""
        assert not control_re.search(name), f"Control char in app_name: {repr(name)}"
        aid = act.get("app_id") or ""
        assert not control_re.search(aid), f"Control char in app_id: {repr(aid)}"


def test_all_normal_records_are_live_source(make_activity_db):
    """Bug 1: in full pipeline, every activity with source='normal' has internal source='live'."""
    from engine.carver.freelist import carve_freelist
    from engine.dedup import deduplicate
    from engine.live_parser import read_activity
    from engine.normalize import normalize_records
    from engine.pages import PageSource

    gt = make_activity_db(n_insert=30, m_delete=10)
    ps = PageSource.from_file(gt["db_path"])
    live = normalize_records(read_activity(gt["db_path"], immutable=True))
    carved = normalize_records(carve_freelist(ps))
    all_records = deduplicate(live, carved)

    result = build_ui_output(all_records, [{"path": gt["db_path"]}],
                              analyzed_at="2026-06-12T00:00:00Z")

    # Build a lookup: activity id → internal source
    id_to_src = {r.get("Id") or "": r.get("source") for r in all_records}

    for act in result["activities"]:
        if act["source"] == "normal":
            internal = id_to_src.get(act["id"], "live")
            assert internal == "live", (
                f"Activity id={act['id']} is 'normal' but internal source={internal!r}"
            )
