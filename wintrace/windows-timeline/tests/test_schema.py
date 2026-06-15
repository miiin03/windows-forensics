"""Tests for engine.schema (Activity column model)."""

from engine.schema import (
    ACTIVITY_COLUMNS,
    ACTIVITY_COLUMN_COUNT,
    ACTIVITY_COLUMN_NAMES,
    DATETIME_COLUMNS,
    JSON_BLOB_COLUMNS,
    GUID_COLUMNS,
    column_index,
    KNOWN_TABLE_COLUMN_COUNTS,
)


def test_activity_has_31_columns():
    assert ACTIVITY_COLUMN_COUNT == 31
    assert len(ACTIVITY_COLUMNS) == 31
    assert len(ACTIVITY_COLUMN_NAMES) == 31


def test_first_column_is_id_guid():
    assert ACTIVITY_COLUMNS[0].name == "Id"
    assert ACTIVITY_COLUMNS[0].role == "guid"


def test_known_columns_present_in_order():
    assert ACTIVITY_COLUMN_NAMES[1] == "AppId"
    assert ACTIVITY_COLUMN_NAMES[4] == "ActivityType"
    assert ACTIVITY_COLUMN_NAMES[5] == "ActivityStatus"
    assert ACTIVITY_COLUMN_NAMES[10] == "LastModifiedTime"
    assert ACTIVITY_COLUMN_NAMES[12] == "Payload"
    assert ACTIVITY_COLUMN_NAMES[-1] == "ETag"


def test_column_index_lookup():
    assert column_index("Id") == 0
    assert column_index("LastModifiedTime") == 10
    assert column_index("ETag") == 30


def test_datetime_columns():
    assert "LastModifiedTime" in DATETIME_COLUMNS
    assert "StartTime" in DATETIME_COLUMNS
    assert "EndTime" in DATETIME_COLUMNS
    assert "LocalExpirationTime" in DATETIME_COLUMNS
    assert "AppId" not in DATETIME_COLUMNS


def test_json_blob_columns():
    assert JSON_BLOB_COLUMNS == ("Payload", "ClipboardPayload", "OriginalPayload")


def test_guid_columns():
    assert "Id" in GUID_COLUMNS
    assert "ParentActivityId" in GUID_COLUMNS


def test_known_table_counts_for_identification():
    assert KNOWN_TABLE_COLUMN_COUNTS["Activity"] == 31
