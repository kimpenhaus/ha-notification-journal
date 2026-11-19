"""Tests of the versioned schema migrations."""

import logging
import os
import sqlite3
import time
from pathlib import Path

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.notification_journal.const import DATABASE_FILE, DEFAULT_OPTIONS, DOMAIN
from custom_components.notification_journal.models import NotificationRecord, Origin, OriginKind
from custom_components.notification_journal.store import (
    MIGRATION_COPY_DAYS,
    SCHEMA_VERSION,
    NewerSchemaError,
    NotificationStore,
    Query,
)

SCHEMA_1 = """
CREATE TABLE notifications (
    rowid INTEGER PRIMARY KEY, id TEXT NOT NULL UNIQUE, time REAL NOT NULL, source TEXT NOT NULL,
    channel TEXT NOT NULL, title TEXT, message TEXT NOT NULL, data TEXT, recipients TEXT NOT NULL,
    origin TEXT NOT NULL, origin_kind TEXT NOT NULL, origin_entity_id TEXT, context_id TEXT NOT NULL,
    status TEXT NOT NULL, error TEXT, grp TEXT, inner_calls TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE notification_users (
    notification INTEGER NOT NULL REFERENCES notifications (rowid) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    PRIMARY KEY (notification, user_id)
) WITHOUT ROWID;
CREATE VIRTUAL TABLE notifications_fts USING fts5 (title, message, channel, people, origin);
"""
ARCHIVE = """
CREATE TABLE notification_archive (
    notification INTEGER NOT NULL REFERENCES notifications (rowid) ON DELETE CASCADE,
    user_id TEXT NOT NULL, time REAL NOT NULL, PRIMARY KEY (notification, user_id)
) WITHOUT ROWID;
"""
ORIGIN = '{"kind": "unknown", "entity_id": null, "name": null, "trace_key": null, "run_id": null, "user_id": null}'


def _old_database(path: Path, version: int) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA_1 + (ARCHIVE if version >= 2 else ""))
    connection.execute(
        "INSERT INTO notifications VALUES (1, 'old', ?, 'notify', 'notify.phone', 'Old', 'Kept', NULL, '[]', ?,"
        " 'unknown', NULL, 'c', 'sent', NULL, NULL, '[]')",
        (time.time() - 60, ORIGIN),
    )
    connection.execute(f"PRAGMA user_version = {version}")
    connection.commit()
    connection.close()


def _columns(path: Path) -> set[str]:
    connection = sqlite3.connect(path)
    try:
        return {row[1] for row in connection.execute("PRAGMA table_info(notifications)")}
    finally:
        connection.close()


def _counts(path: Path) -> list[tuple[str, str, int]]:
    connection = sqlite3.connect(path)
    try:
        return connection.execute("SELECT user_id, origin, notifications FROM notification_counts").fetchall()
    finally:
        connection.close()


def _version(path: Path) -> int:
    connection = sqlite3.connect(path)
    try:
        return connection.execute("PRAGMA user_version").fetchone()[0]
    finally:
        connection.close()


def _backups(folder: Path) -> list[Path]:
    return list(folder.glob("*.bak-*"))


async def test_new_database_gets_the_current_schema(tmp_path: Path) -> None:
    store = NotificationStore(str(tmp_path / "new.db"))
    await store.async_open()
    await store.async_close()

    assert _version(tmp_path / "new.db") == SCHEMA_VERSION
    assert {"source_ref", "status_time", "status_by", "answers", "origin_key"} <= _columns(tmp_path / "new.db")
    assert not _backups(tmp_path)


@pytest.mark.parametrize("version", [1, 2])
async def test_old_database_is_migrated_after_a_backup(tmp_path: Path, version: int) -> None:
    path = tmp_path / "old.db"
    _old_database(path, version)

    store = NotificationStore(str(path))
    await store.async_open()
    records = (await store.async_query(Query())).records
    await store.async_set_archived(["old"], "user", archived=True, visible_to=None)
    await store.async_close()

    assert [r.message for r in records] == ["Kept"]
    assert records[0].answers == []
    assert _version(path) == SCHEMA_VERSION
    assert {"source_ref", "status_time", "status_by", "answers", "origin_key"} <= _columns(path)
    assert _counts(path) == [("", "unknown", 1)]
    backup = tmp_path / f"old.db.bak-v{version}"
    assert _version(backup) == version
    assert "source_ref" not in _columns(backup)


async def test_database_of_a_newer_version_is_left_untouched(tmp_path: Path) -> None:
    path = tmp_path / "newer.db"
    _old_database(path, 2)
    connection = sqlite3.connect(path)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    connection.commit()
    connection.close()
    before = path.read_bytes()

    store = NotificationStore(str(path))
    with pytest.raises(NewerSchemaError):
        await store.async_open()
    await store.async_close()

    assert path.read_bytes() == before
    assert "source_ref" not in _columns(path)


async def test_setup_fails_on_a_newer_database(hass: HomeAssistant, config_dir: Path) -> None:
    connection = sqlite3.connect(config_dir / DATABASE_FILE)
    connection.executescript(SCHEMA_1)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    connection.commit()
    connection.close()
    entry = MockConfigEntry(domain=DOMAIN, options=DEFAULT_OPTIONS)
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_migration_adds_missing_schema_objects(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    _old_database(path, 1)

    store = NotificationStore(str(path))
    await store.async_open()
    await store.async_close()

    connection = sqlite3.connect(path)
    try:
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
    finally:
        connection.close()
    assert {"notifications_delete", "notifications_time", "notification_users_user"} <= names


def _copy(folder: Path, name: str, days_old: float) -> Path:
    path = folder / name
    path.write_bytes(b"copy")
    stamp = time.time() - days_old * 86400
    os.utime(path, (stamp, stamp))
    return path


async def _open_and_close(path: Path) -> None:
    store = NotificationStore(str(path))
    await store.async_open()
    await store.async_close()


async def test_copies_of_earlier_migrations_are_removed(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    path = tmp_path / "journal.db"
    await _open_and_close(path)
    first = _copy(tmp_path, "journal.db.bak-v1", days_old=40)
    second = _copy(tmp_path, "journal.db.bak-v2", days_old=20)
    latest = _copy(tmp_path, "journal.db.bak-v10", days_old=1)

    with caplog.at_level(logging.DEBUG):
        await _open_and_close(path)

    assert not first.exists()
    assert not second.exists()
    assert latest.exists()
    assert f"Removed {first}" in caplog.text


async def test_copy_of_the_latest_migration_is_removed_after_the_grace_period(tmp_path: Path) -> None:
    path = tmp_path / "journal.db"
    await _open_and_close(path)
    young = _copy(tmp_path, "journal.db.bak-v3", days_old=MIGRATION_COPY_DAYS - 1)

    await _open_and_close(path)
    assert young.exists()

    stamp = time.time() - (MIGRATION_COPY_DAYS + 1) * 86400
    os.utime(young, (stamp, stamp))
    await _open_and_close(path)
    assert not young.exists()


async def test_copy_made_by_a_migration_is_kept(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    _old_database(path, 1)
    earlier = _copy(tmp_path, "old.db.bak-v0", days_old=1)

    await _open_and_close(path)

    assert _backups(tmp_path) == [tmp_path / "old.db.bak-v1"]
    assert not earlier.exists()


async def test_other_files_are_left_alone(tmp_path: Path) -> None:
    path = tmp_path / "journal.db"
    await _open_and_close(path)
    others = [
        _copy(tmp_path, name, days_old=100)
        for name in ("other.db.bak-v1", "journal.db.bak-v1-journal", "journal.db.bak-vX", "journal.db.bak")
    ]

    await _open_and_close(path)

    assert all(other.exists() for other in others)


async def test_failed_notifications_count_after_the_step_to_version_6(tmp_path: Path) -> None:
    path = tmp_path / "v5.db"
    store = NotificationStore(str(path))
    await store.async_open()
    store.add(
        NotificationRecord(
            id="lost",
            time=dt_util.utcnow(),
            source="notify",
            channel="notify.phone",
            title=None,
            message="Lost",
            data=None,
            recipients=[],
            origin=Origin(kind=OriginKind.UNKNOWN),
            context_id="c",
        )
    )
    store.mark_failed("lost", None, "Chat not found")
    await store.async_close()
    connection = sqlite3.connect(path)
    with connection:
        connection.execute("ALTER TABLE notification_counts DROP COLUMN failed")
        connection.execute("PRAGMA user_version = 5")
    connection.close()

    store = NotificationStore(str(path))
    await store.async_open()
    await store.async_close()

    connection = sqlite3.connect(path)
    try:
        assert connection.execute("SELECT user_id, notifications, failed FROM notification_counts").fetchall() == [
            ("", 1, 1)
        ]
    finally:
        connection.close()
    assert _version(path) == SCHEMA_VERSION
