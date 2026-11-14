"""Tests of the versioned schema migrations."""

import sqlite3
import time
from pathlib import Path

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.notification_journal.const import DATABASE_FILE, DEFAULT_OPTIONS, DOMAIN
from custom_components.notification_journal.store import (
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
    assert {"source_ref", "status_time", "status_by"} <= _columns(tmp_path / "new.db")
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
    assert _version(path) == SCHEMA_VERSION
    assert {"source_ref", "status_time", "status_by"} <= _columns(path)
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
