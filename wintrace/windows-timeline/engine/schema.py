"""ActivitiesCache.db schema model.

The ``Activity`` table is the forensic centrepiece. Columns are listed in
*declared order* (the order serial types appear in a record header), which the
carver relies on to map recovered columns back to names without a schema.
"""

from __future__ import annotations

from dataclasses import dataclass

Role = str  # one of: guid, text, int, datetime, blob_json


@dataclass(frozen=True)
class Column:
    name: str
    decl_type: str
    role: Role


# Declared order from PRAGMA table_info(Activity) on a real ActivitiesCache.db.
ACTIVITY_COLUMNS: tuple[Column, ...] = (
    Column("Id", "GUID", "guid"),
    Column("AppId", "TEXT", "text"),
    Column("PackageIdHash", "TEXT", "text"),
    Column("AppActivityId", "TEXT", "text"),
    Column("ActivityType", "INT", "int"),
    Column("ActivityStatus", "INT", "int"),
    Column("ParentActivityId", "GUID", "guid"),
    Column("Tag", "TEXT", "text"),
    Column("Group", "TEXT", "text"),
    Column("MatchId", "TEXT", "text"),
    Column("LastModifiedTime", "DATETIME", "datetime"),
    Column("ExpirationTime", "DATETIME", "datetime"),
    Column("Payload", "BLOB", "blob_json"),
    Column("Priority", "INT", "int"),
    Column("IsLocalOnly", "INT", "int"),
    Column("PlatformDeviceId", "TEXT", "text"),
    Column("DdsDeviceId", "TEXT", "text"),
    Column("CreatedInCloud", "DATETIME", "datetime"),
    Column("StartTime", "DATETIME", "datetime"),
    Column("EndTime", "DATETIME", "datetime"),
    Column("LastModifiedOnClient", "DATETIME", "datetime"),
    Column("GroupAppActivityId", "TEXT", "text"),
    Column("ClipboardPayload", "BLOB", "blob_json"),
    Column("EnterpriseId", "TEXT", "text"),
    Column("OriginalPayload", "BLOB", "blob_json"),
    Column("UserActionState", "INT", "int"),
    Column("IsRead", "INT", "int"),
    Column("OriginalLastModifiedOnClient", "DATETIME", "datetime"),
    Column("GroupItems", "TEXT", "text"),
    Column("LocalExpirationTime", "DATETIME", "datetime"),
    Column("ETag", "INT", "int"),
)

ACTIVITY_COLUMN_COUNT = len(ACTIVITY_COLUMNS)
ACTIVITY_COLUMN_NAMES = tuple(c.name for c in ACTIVITY_COLUMNS)

DATETIME_COLUMNS = frozenset(c.name for c in ACTIVITY_COLUMNS if c.role == "datetime")
GUID_COLUMNS = frozenset(c.name for c in ACTIVITY_COLUMNS if c.role == "guid")
JSON_BLOB_COLUMNS = ("Payload", "ClipboardPayload", "OriginalPayload")

_INDEX = {c.name: i for i, c in enumerate(ACTIVITY_COLUMNS)}

# Column counts for other tables, used to disambiguate a carved cell that
# carries no table identity. Activity's 31 + the GUID fingerprint is distinctive.
KNOWN_TABLE_COLUMN_COUNTS = {
    "Activity": 31,
    "ActivityOperation": 17,
    "Activity_PackageId": 4,
    "AppSettings": 3,
    "Metadata": 2,
}


def column_index(name: str) -> int:
    return _INDEX[name]


# Known ActivityType codes (best-effort labels for the viewer).
ACTIVITY_TYPE_LABELS = {
    2: "Notification",
    3: "Mobile deep-link / backgrounded",
    5: "Open app / foreground (UserEngaged)",
    6: "App-in-use / in-progress",
    10: "Clipboard",
    11: "Copy/paste",
    16: "Copy/paste (clipboard)",
}
