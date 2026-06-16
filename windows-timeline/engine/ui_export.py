"""Convert normalized Activity records to the UI contract JSON (--ui output).

Reference: windows-timeline/UI-CONTRACT.md
The viewer (index.html, "Windows Activity Forensics 통합 타임라인 v0.3") reads
exactly this schema; no viewer code changes are needed.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

_KST = timezone(timedelta(hours=9))
_UTC = timezone.utc

# Lower bound: Windows 10 launched in 2015; 2010 gives generous margin.
_MIN_DT = datetime(2010, 1, 1, tzinfo=timezone.utc)

# Only strip render-breaking control chars. U+FFFD (replacement char) is
# intentionally kept: it marks bytes that couldn't be decoded, giving the
# examiner forensic visibility into partially-recovered carved text.
_RE_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

_FRIENDLY_NAMES: dict[str, str] = {
    "WINWORD.EXE": "Microsoft Word",
    "EXCEL.EXE": "Microsoft Excel",
    "POWERPNT.EXE": "Microsoft PowerPoint",
    "ONENOTE.EXE": "Microsoft OneNote",
    "OUTLOOK.EXE": "Microsoft Outlook",
    "MSEDGE.EXE": "Microsoft Edge",
    "MSEDGEWEBVIEW2.EXE": "Microsoft Edge WebView2",
    "CHROME.EXE": "Google Chrome",
    "FIREFOX.EXE": "Mozilla Firefox",
    "IEXPLORE.EXE": "Internet Explorer",
    "EXPLORER.EXE": "Windows Explorer",
    "CODE.EXE": "Visual Studio Code",
    "NOTEPAD.EXE": "Notepad",
    "NOTEPAD++.EXE": "Notepad++",
    "MSPAINT.EXE": "Microsoft Paint",
    "CALC.EXE": "Calculator",
    "CMD.EXE": "Command Prompt",
    "POWERSHELL.EXE": "PowerShell",
    "PWSH.EXE": "PowerShell Core",
    "MSTSC.EXE": "Remote Desktop",
    "ACRORD32.EXE": "Adobe Acrobat Reader",
    "ACROBAT.EXE": "Adobe Acrobat",
    "PHOTOSHOP.EXE": "Adobe Photoshop",
    "TEAMS.EXE": "Microsoft Teams",
    "SLACK.EXE": "Slack",
    "ZOOM.EXE": "Zoom",
    "WINSCP.EXE": "WinSCP",
    "PUTTY.EXE": "PuTTY",
    "DEVENV.EXE": "Visual Studio",
    "PYCHARM64.EXE": "PyCharm",
}

_RE_FILE_URI = re.compile(r"\bfile://[^\s\"'<>\\]+", re.IGNORECASE)
_RE_HTTP_URL = re.compile(r"\bhttps?://[^\s\"'<>\\]+", re.IGNORECASE)
_RE_CAMEL = re.compile(r"([a-z])([A-Z])")

# ── String sanitation ─────────────────────────────────────────────────────────

def _strip_control(s: str | None) -> str | None:
    """Remove render-breaking control chars (0x00-0x1F, 0x7F). Keep U+FFFD."""
    if not s:
        return None
    cleaned = _RE_CONTROL.sub("", s).strip()
    return cleaned or None


# ── UTC → KST ─────────────────────────────────────────────────────────────────

def _utc_to_kst(iso_utc: str | None) -> str | None:
    """Unconditional UTC → KST ISO8601 (for meta fields like analyzed_at_kst)."""
    if not iso_utc:
        return None
    try:
        dt = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
        return dt.astimezone(_KST).isoformat()
    except (ValueError, TypeError, AttributeError):
        return None


def _ts_kst(iso_utc: str | None, max_dt: datetime) -> str | None:
    """UTC → KST with rolling date guard [_MIN_DT, max_dt].

    Returns None for epoch-0 / pre-2010 dates and for anything after max_dt
    (analysis time + 2-day clock-skew margin).  Year-granular upper bounds
    let whole future years through; this catches same-year future dates too.
    """
    if not iso_utc:
        return None
    try:
        dt = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
        if dt < _MIN_DT or dt > max_dt:
            return None
        return dt.astimezone(_KST).isoformat()
    except (ValueError, TypeError, AttributeError):
        return None


# ── AppId → app_id / app_name ─────────────────────────────────────────────────

def _title_from_exe(exe: str) -> str:
    base = exe[:-4] if exe.upper().endswith(".EXE") else exe
    return base.replace("-", " ").replace("_", " ").title()


def _parse_appid(appid_raw: str | None) -> tuple[str | None, str | None]:
    """Return (app_id, app_name) from a normalized AppId JSON string.

    Control chars are stripped; U+FFFD is kept so partially-recovered text
    remains visible in the viewer rather than being silently discarded.
    """
    if not appid_raw:
        return None, None

    try:
        parsed = json.loads(appid_raw)
    except (json.JSONDecodeError, TypeError):
        # Not valid JSON — strip control chars, keep whatever readable text remains
        cleaned = _strip_control(appid_raw)
        return (cleaned, cleaned) if cleaned else (None, None)

    entries = parsed if isinstance(parsed, list) else [parsed]
    if not entries or not isinstance(entries[0], dict):
        return None, None

    first = entries[0]
    # Strip control chars from the application path; U+FFFD stays.
    app = _strip_control(str(first.get("application") or "")) or ""
    platform = str(first.get("platform") or "")

    if not app:
        return None, None

    if "win32" in platform.lower():
        exe = app.replace("\\", "/").rsplit("/", 1)[-1].upper()
        exe_clean = _strip_control(exe)
        if not exe_clean:
            return None, None
        friendly = _FRIENDLY_NAMES.get(exe_clean, _title_from_exe(exe_clean))
        return exe_clean, friendly

    # Package ID / Universal App — strip version/publisher suffix
    pkg = app.split("_")[0]
    pkg_clean = _strip_control(pkg)
    if not pkg_clean:
        return None, None
    parts = pkg_clean.split(".")
    raw = parts[-1] if len(parts) > 1 else pkg_clean
    name = _RE_CAMEL.sub(r"\1 \2", raw).strip()
    return _strip_control(app) or None, name or pkg_clean or None


# ── Payload helpers ───────────────────────────────────────────────────────────

def _payload_str(record: dict) -> str:
    payload = record.get("Payload") or {}
    parsed = payload.get("parsed")
    if parsed is None:
        return payload.get("raw") or ""
    return json.dumps(parsed) if not isinstance(parsed, str) else parsed


def _category(record: dict) -> str:
    clipboard = (record.get("ClipboardPayload") or {}).get("parsed")
    if clipboard is not None:
        return "file_open"

    ps = _payload_str(record)
    if _RE_FILE_URI.search(ps):
        return "file_open"
    if _RE_HTTP_URL.search(ps):
        return "web_visit"
    return "app_exec"


def _title(record: dict) -> str | None:
    payload = record.get("Payload") or {}
    parsed = payload.get("parsed")
    if isinstance(parsed, dict):
        for key in ("displayText", "description", "content", "text"):
            val = parsed.get(key)
            if val:
                return str(val)
    return None


def _url(record: dict) -> str | None:
    ps = _payload_str(record)
    m = _RE_FILE_URI.search(ps)
    if m:
        return m.group(0).rstrip('\\")]},')
    m = _RE_HTTP_URL.search(ps)
    if m:
        return m.group(0).rstrip('\\")]},')
    return None


# ── Record-level field mappings ───────────────────────────────────────────────

def _ui_source(record: dict) -> str:
    """Map internal source → UI source.

    Only records whose internal source is "live" are "normal".
    All carver sources (freelist/freelist_brute/freeblock/wal/wal_stale/slack)
    map to "carved" regardless of is_deleted — WAL prior-version records can
    have is_deleted=False yet still come from a carver.
    """
    return "normal" if record.get("source") == "live" else "carved"


def _payload_format(record: dict) -> str:
    src = record.get("source", "live")
    if src == "live":
        return "json"
    if src in ("wal", "wal_stale"):
        return "wal_frame"
    return "sqlite_cell"


def _confidence(record: dict) -> str:
    label = record.get("confidence_label", "high")
    return label if label in ("high", "medium", "low", "very_low") else "low"


def _record_id(record: dict) -> str:
    guid = record.get("Id")
    if guid:
        return guid
    prov = record.get("provenance") or {}
    page_no = prov.get("page_no")
    if page_no is not None:
        return f"page-{page_no}-off{prov.get('cell_offset', 0)}"
    rowid = prov.get("rowid")
    if rowid is not None:
        return f"live-rowid-{rowid}"
    import hashlib
    key = f"{record.get('source')}-{record.get('ActivityType')}-{record.get('app_name')}"
    return "rec-" + hashlib.md5(key.encode()).hexdigest()[:12]


def _detail(record: dict) -> str | None:
    src = record.get("source", "live")
    if src == "live":
        return None
    prov = record.get("provenance") or {}
    page_no = prov.get("page_no")
    cell_off = prov.get("cell_offset")

    if src in ("wal", "wal_stale"):
        suffix = " (stale)" if src == "wal_stale" else ""
        return f"WAL 구버전(삭제/수정 전){suffix}"

    parts = [src]
    if page_no is not None:
        parts.append(f"p{page_no}")
    if cell_off is not None:
        parts.append(f"off{cell_off}")
    return " ".join(parts)


# ── Core converter ────────────────────────────────────────────────────────────

def _to_activity(record: dict, *, max_dt: datetime) -> dict:
    app_id, app_name = _parse_appid(record.get("AppId_raw"))
    if not app_name:
        app_name = _strip_control(record.get("app_name"))

    ts = record.get("timestamps") or {}
    start_iso = (ts.get("StartTime") or {}).get("iso8601")
    end_iso = (ts.get("EndTime") or {}).get("iso8601")
    lmt_iso = (ts.get("LastModifiedTime") or {}).get("iso8601")

    return {
        "id": _record_id(record),
        "artifact": "timeline",
        "category": _category(record),
        "source": _ui_source(record),
        "source_browser": None,
        "payload_format": _payload_format(record),
        "confidence": _confidence(record),
        "decrypted": None,
        "app_id": app_id,
        "app_name": app_name or app_id,
        "title": _strip_control(_title(record)),
        "url": _strip_control(_url(record)),
        "detail": _detail(record),
        "secret_value": None,
        "start_time_kst": _ts_kst(start_iso, max_dt),
        "end_time_kst": _ts_kst(end_iso, max_dt),
        "last_modified_kst": _ts_kst(lmt_iso, max_dt),
        "raw_payload_b64": None,
    }


def build_ui_output(
    records: list[dict],
    source_files: list[dict],
    *,
    analyzed_at: str | None = None,
    evidence: list[dict] | None = None,
) -> dict:
    """Convert normalize_records() output to the UI contract JSON.

    Args:
        records: All normalized Activity records (live + carved combined).
        source_files: Source file info dicts from the CLI pipeline.
        analyzed_at: UTC ISO8601 timestamp; defaults to now.
        evidence: Chain-of-custody hash records for the source evidence files.

    Returns:
        Dict matching the UI contract schema in UI-CONTRACT.md.
    """
    if analyzed_at is None:
        analyzed_at = datetime.now(tz=_UTC).isoformat().replace("+00:00", "Z")

    try:
        analyzed_dt = datetime.fromisoformat(analyzed_at.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        analyzed_dt = datetime.now(tz=_UTC)
    # Activity timestamps must not exceed analysis time + 2-day clock-skew margin.
    max_dt = analyzed_dt + timedelta(days=2)

    activities = [_to_activity(r, max_dt=max_dt) for r in records]
    normal_n = sum(1 for a in activities if a["source"] == "normal")
    carved_n = sum(1 for a in activities if a["source"] == "carved")

    sources_meta = [
        {
            "artifact": "timeline",
            "path": sf.get("path", ""),
            "records": len(records),
        }
        for sf in (source_files or [{}])
    ]

    return {
        "meta": {
            "tool": "WinActivityForensics",
            "version": "0.3",
            "sources": sources_meta,
            "analyzed_at_kst": _utc_to_kst(analyzed_at),
            "timezone": "Asia/Seoul (UTC+9)",
            "evidence": evidence or [],
            "stats": {
                "total": len(activities),
                "normal": normal_n,
                "carved": carved_n,
                "encrypted_skipped": 0,
                "decrypted_ok": 0,
                "by_artifact": {"timeline": len(activities)},
            },
        },
        "activities": activities,
    }
