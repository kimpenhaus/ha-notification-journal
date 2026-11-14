"""Keep the recorded notifications in an SQLite database of their own."""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from .models import (
    EVERYONE,
    Answer,
    Call,
    NotificationRecord,
    Origin,
    Status,
    answer_from_dict,
    call_from_dict,
    origin_from_dict,
    recipient_from_dict,
)

_LOGGER = logging.getLogger(__name__)

SCHEMA_VERSION = 4
VISIBLE_TO_USER = f"rowid IN (SELECT notification FROM notification_users WHERE user_id IN (?, '{EVERYONE}'))"
BACKUP_PAUSE_LIMIT = 1800
ORIGIN_GROUP = "coalesce(origin_entity_id, 'integration.' || json_extract(origin, '$.integration'), origin_kind)"

SCHEMA = """
CREATE TABLE IF NOT EXISTS notifications (
    rowid INTEGER PRIMARY KEY,
    id TEXT NOT NULL UNIQUE,
    time REAL NOT NULL,
    source TEXT NOT NULL,
    channel TEXT NOT NULL,
    title TEXT,
    message TEXT NOT NULL,
    data TEXT,
    recipients TEXT NOT NULL,
    origin TEXT NOT NULL,
    origin_kind TEXT NOT NULL,
    origin_entity_id TEXT,
    context_id TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    grp TEXT,
    inner_calls TEXT NOT NULL DEFAULT '[]',
    source_ref TEXT,
    status_time REAL,
    status_by TEXT,
    answers TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS notifications_time ON notifications (time);
CREATE INDEX IF NOT EXISTS notifications_origin ON notifications (origin_entity_id);
CREATE TABLE IF NOT EXISTS notification_users (
    notification INTEGER NOT NULL REFERENCES notifications (rowid) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    PRIMARY KEY (notification, user_id)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS notification_users_user ON notification_users (user_id);
CREATE TABLE IF NOT EXISTS notification_archive (
    notification INTEGER NOT NULL REFERENCES notifications (rowid) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    time REAL NOT NULL,
    PRIMARY KEY (notification, user_id)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS notification_archive_user ON notification_archive (user_id);
CREATE INDEX IF NOT EXISTS notifications_source_ref ON notifications (source, source_ref) WHERE source_ref IS NOT NULL;
CREATE VIRTUAL TABLE IF NOT EXISTS notifications_fts USING fts5 (title, message, channel, people, origin);
CREATE TRIGGER IF NOT EXISTS notifications_delete AFTER DELETE ON notifications BEGIN
    DELETE FROM notifications_fts WHERE rowid = old.rowid;
END;
"""

MIGRATIONS: dict[int, tuple[str, ...]] = {
    2: (
        """CREATE TABLE notification_archive (
            notification INTEGER NOT NULL REFERENCES notifications (rowid) ON DELETE CASCADE,
            user_id TEXT NOT NULL,
            time REAL NOT NULL,
            PRIMARY KEY (notification, user_id)
        ) WITHOUT ROWID""",
        "CREATE INDEX notification_archive_user ON notification_archive (user_id)",
    ),
    3: (
        "ALTER TABLE notifications ADD COLUMN source_ref TEXT",
        "ALTER TABLE notifications ADD COLUMN status_time REAL",
        "ALTER TABLE notifications ADD COLUMN status_by TEXT",
        "CREATE INDEX notifications_source_ref ON notifications (source, source_ref) WHERE source_ref IS NOT NULL",
    ),
    4: ("ALTER TABLE notifications ADD COLUMN answers TEXT NOT NULL DEFAULT '[]'",),
}
"""The steps from the previous schema version to each version; a new version adds its step here."""


class NewerSchemaError(RuntimeError):
    """The database was written by a newer version of the integration."""


@dataclass(slots=True, kw_only=True)
class Query:
    """What to list: filters, order and page."""

    user_id: str | None = None
    text: str | None = None
    channel: str | None = None
    origin_entity_id: str | None = None
    status: Status | None = None
    since: datetime | None = None
    until: datetime | None = None
    newest_first: bool = True
    group_by_origin: bool = False
    archive_user_id: str | None = None
    archived: bool = False
    limit: int = 50
    offset: int = 0
    with_counts: bool = True
    """Count the matches (and per origin); a further page of the same list needs no counts."""


@dataclass(slots=True)
class Page:
    """One page of records and the number of all that match."""

    records: list[NotificationRecord]
    total: int | None
    groups: dict[str, int] | None = None


def _fts_query(text: str) -> str | None:
    terms = ['"' + term.replace('"', '""') + '"*' for term in text.split() if any(ch.isalnum() for ch in term)]
    return " AND ".join(terms) or None


def _people(record: NotificationRecord) -> str:
    return " ".join(sorted({r.name for r in record.all_recipients}))


class NotificationStore:
    """Write and read notifications; every database access runs in one worker thread, in order.

    Writes come from event listeners and are only submitted; their order is kept because a single
    thread executes them. During a backup the worker waits, so the file on disk stays consistent.
    """

    def __init__(self, path: str) -> None:
        """Prepare the store; async_open opens the database."""
        self._path = path
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="notification_journal")
        self._connection: sqlite3.Connection | None = None
        self._pending: set[Future[Any]] = set()
        self._resume = threading.Event()
        self._listeners: list[Callable[[str, str], None]] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    async def async_open(self) -> None:
        """Open the database and create the schema."""
        self._loop = asyncio.get_running_loop()
        await self._run(self._open)

    def async_add_listener(self, listener: Callable[[str, str], None]) -> Callable[[], None]:
        """Call listener(change, record_id) once a record was added, changed or removed; return the remover."""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    async def async_close(self) -> None:
        """Finish pending writes and close the database."""
        self._resume.set()
        await self.async_flush()
        await self._run(self._close)
        self._executor.shutdown(wait=False)

    async def async_flush(self) -> None:
        """Wait until every submitted write is done."""
        while self._pending:
            await asyncio.wait([asyncio.wrap_future(f) for f in list(self._pending)])

    def add(self, record: NotificationRecord) -> None:
        """Submit a new record."""
        self._submit(self._insert, record, notify=("added", record.id))

    async def async_set_archived(
        self, record_ids: list[str], user_id: str, *, archived: bool, visible_to: str | None
    ) -> int:
        """Archive records for one user, or restore them; only records visible_to that user count, if given."""
        return await self._run(self._set_archived, record_ids, user_id, archived, visible_to)

    async def async_delete(self, record_id: str) -> bool:
        """Delete a record; return whether it existed."""
        deleted = await self._run(self._delete, record_id)
        if deleted:
            self._notify("removed", record_id)
        return deleted

    def add_inner_call(self, record_id: str, call: Call) -> None:
        """Submit a call a group made for one of its members."""
        self._submit(self._append_call, record_id, call, notify=("updated", record_id))

    def set_status(self, record_id: str, status: Status, time: datetime, by: Origin | None) -> None:
        """Submit a change of status, with when and by whom it happened."""
        self._submit(self._update_status, record_id, status, time, by, notify=("updated", record_id))

    async def async_add_answer(self, source: str, answer: Answer) -> str | None:
        """Attach an answer to the latest record of a source that offered its button; return that record's id.

        A record that reached the user who answered comes first; an action ID used by several
        notifications belongs to the most recent one.
        """
        record_id = await self._run(self._add_answer, source, answer)
        if record_id is not None:
            self._notify("updated", record_id)
        return record_id

    async def async_open_records(self, source: str) -> dict[str, tuple[str, datetime]]:
        """Return the records of a source that are still open, as {source_ref: (record id, time)}."""
        return await self._run(self._open_records, source)

    async def async_facets(self, user_id: str | None) -> dict[str, list[dict[str, str | None]]]:
        """Return the automations and scripts that sent notifications, limited to a user's records if given."""
        return await self._run(self._facets, user_id)

    async def async_get(self, record_id: str) -> NotificationRecord | None:
        """Return one record."""
        return await self._run(self._get, record_id)

    async def async_query(self, query: Query) -> Page:
        """Return the records that match a query."""
        return await self._run(self._query, query)

    async def async_purge(self, retention_days: int, max_entries: int) -> int:
        """Delete records older than the retention and beyond the maximum number; return how many."""
        cutoff = (dt_util.utcnow() - timedelta(days=retention_days)).timestamp()
        removed = await self._run(self._purge, cutoff, max_entries)
        if removed:
            self._notify("purged", "")
        return removed

    async def async_pause_for_backup(self) -> None:
        """Write the WAL into the database file and hold every further access until resumed."""
        await self.async_flush()
        self._resume.clear()
        await self._run(self._checkpoint)
        self._executor.submit(self._wait_for_resume)

    def resume_after_backup(self) -> None:
        """Let the held accesses run again."""
        self._resume.set()

    def _submit(self, function: Callable[..., Any], *args: Any, notify: tuple[str, str]) -> None:
        future = self._executor.submit(function, *args)
        self._pending.add(future)
        future.add_done_callback(lambda done: self._done(done, notify))

    def _done(self, future: Future[Any], notify: tuple[str, str]) -> None:
        self._pending.discard(future)
        if (error := future.exception()) is not None:
            _LOGGER.warning("Could not store a notification: %s", error)
            return
        if self._loop is not None and self._listeners:
            self._loop.call_soon_threadsafe(self._notify, *notify)

    def _notify(self, change: str, record_id: str) -> None:
        for listener in list(self._listeners):
            listener(change, record_id)

    async def _run[T](self, function: Callable[..., T], *args: Any) -> T:
        return await asyncio.get_running_loop().run_in_executor(self._executor, function, *args)

    def _db(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("The Notification Journal database is not open")
        return self._connection

    def _open(self) -> None:
        connection = sqlite3.connect(self._path, check_same_thread=False)
        try:
            self._migrate(connection)
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA foreign_keys = ON")
        except BaseException:
            connection.close()
            raise
        self._connection = connection

    def _migrate(self, connection: sqlite3.Connection) -> None:
        """Create a new database, or bring an older one to SCHEMA_VERSION step by step after a backup."""
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if connection.execute("SELECT 1 FROM sqlite_master WHERE name = 'notifications'").fetchone() is None:
            connection.executescript(SCHEMA)
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            return
        if version > SCHEMA_VERSION:
            raise NewerSchemaError(
                f"{self._path} has schema version {version}, this version of the integration knows "
                f"{SCHEMA_VERSION}; it was left untouched"
            )
        version = max(version, 1)
        if version == SCHEMA_VERSION:
            return
        backup = sqlite3.connect(f"{self._path}.bak-v{version}")
        with backup:
            connection.backup(backup)
        backup.close()
        for step in range(version + 1, SCHEMA_VERSION + 1):
            connection.execute("BEGIN")
            try:
                for statement in MIGRATIONS[step]:
                    connection.execute(statement)
                connection.execute(f"PRAGMA user_version = {step}")
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            _LOGGER.info("Migrated %s to schema version %s", self._path, step)
        connection.executescript(SCHEMA)

    def _close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _checkpoint(self) -> None:
        self._db().execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def _wait_for_resume(self) -> None:
        if not self._resume.wait(BACKUP_PAUSE_LIMIT):
            _LOGGER.warning("Backup did not finish within %s seconds; recording continues", BACKUP_PAUSE_LIMIT)

    def _insert(self, record: NotificationRecord) -> None:
        db = self._db()
        with db:
            cursor = db.execute(
                """INSERT INTO notifications (id, time, source, channel, title, message, data, recipients, origin,
                       origin_kind, origin_entity_id, context_id, status, error, grp, inner_calls, source_ref,
                       status_time, status_by, answers)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.id,
                    record.time.timestamp(),
                    record.source,
                    record.channel,
                    record.title,
                    record.message,
                    None if record.data is None else json.dumps(record.data),
                    json.dumps([asdict(r) for r in record.recipients]),
                    json.dumps(asdict(record.origin)),
                    record.origin.kind.value,
                    record.origin.entity_id,
                    record.context_id,
                    record.status.value,
                    record.error,
                    record.group,
                    json.dumps([asdict(c) for c in record.inner_calls]),
                    record.source_ref,
                    record.status_time.timestamp() if record.status_time else None,
                    json.dumps(asdict(record.status_by)) if record.status_by else None,
                    json.dumps([answer.as_dict() for answer in record.answers]),
                ),
            )
            rowid = cursor.lastrowid
            self._index(db, rowid, record)

    def _append_call(self, record_id: str, call: Call) -> None:
        db = self._db()
        with db:
            row = db.execute("SELECT rowid FROM notifications WHERE id = ?", (record_id,)).fetchone()
            if row is None:
                return
            db.execute(
                "UPDATE notifications SET inner_calls = json_insert(inner_calls, '$[#]', json(?)) WHERE rowid = ?",
                (json.dumps(asdict(call)), row[0]),
            )
            record = self._get_by_rowid(db, row[0])
            if record is not None:
                self._index(db, row[0], record)

    def _update_status(self, record_id: str, status: Status, time: datetime, by: Origin | None) -> None:
        db = self._db()
        with db:
            db.execute(
                "UPDATE notifications SET status = ?, status_time = ?, status_by = ? WHERE id = ?",
                (status.value, time.timestamp(), json.dumps(asdict(by)) if by else None, record_id),
            )

    def _add_answer(self, source: str, answer: Answer) -> str | None:
        db = self._db()
        offered = (
            "SELECT rowid, id FROM notifications WHERE source = ? AND EXISTS "
            "(SELECT 1 FROM json_each(data, '$.data.actions') WHERE json_extract(value, '$.action') = ?)"
        )
        newest = " ORDER BY time DESC, rowid DESC LIMIT 1"
        row = None
        if answer.user_id is not None:
            row = db.execute(
                f"{offered} AND rowid IN (SELECT notification FROM notification_users WHERE user_id = ?){newest}",
                (source, answer.action, answer.user_id),
            ).fetchone()
        if row is None:
            row = db.execute(offered + newest, (source, answer.action)).fetchone()
        if row is None:
            return None
        with db:
            db.execute(
                "UPDATE notifications SET answers = json_insert(answers, '$[#]', json(?)) WHERE rowid = ?",
                (json.dumps(answer.as_dict()), row[0]),
            )
        return row[1]

    def _open_records(self, source: str) -> dict[str, tuple[str, datetime]]:
        rows = self._db().execute(
            "SELECT source_ref, id, time FROM notifications WHERE source = ? AND source_ref IS NOT NULL AND status = ?",
            (source, Status.SENT.value),
        )
        return {ref: (record_id, dt_util.utc_from_timestamp(time)) for ref, record_id, time in rows}

    @staticmethod
    def _index(db: sqlite3.Connection, rowid: int | None, record: NotificationRecord) -> None:
        db.executemany(
            "INSERT OR IGNORE INTO notification_users (notification, user_id) VALUES (?, ?)",
            [(rowid, user_id) for user_id in record.user_ids],
        )
        db.execute("DELETE FROM notifications_fts WHERE rowid = ?", (rowid,))
        db.execute(
            "INSERT INTO notifications_fts (rowid, title, message, channel, people, origin) VALUES (?, ?, ?, ?, ?, ?)",
            (rowid, record.title or "", record.message, record.channel, _people(record), record.origin.name or ""),
        )

    def _set_archived(self, record_ids: list[str], user_id: str, archived: bool, visible_to: str | None) -> int:
        db = self._db()
        marks = ", ".join("?" * len(record_ids))
        scope = f" AND {VISIBLE_TO_USER}" if visible_to else ""
        rows = db.execute(
            f"SELECT rowid FROM notifications WHERE id IN ({marks}){scope}",
            [*record_ids, *([visible_to] if visible_to else [])],
        ).fetchall()
        with db:
            if archived:
                now = dt_util.utcnow().timestamp()
                cursor = db.executemany(
                    "INSERT OR IGNORE INTO notification_archive (notification, user_id, time) VALUES (?, ?, ?)",
                    [(rowid, user_id, now) for (rowid,) in rows],
                )
            else:
                cursor = db.executemany(
                    "DELETE FROM notification_archive WHERE notification = ? AND user_id = ?",
                    [(rowid, user_id) for (rowid,) in rows],
                )
        return cursor.rowcount

    def _delete(self, record_id: str) -> bool:
        db = self._db()
        with db:
            return db.execute("DELETE FROM notifications WHERE id = ?", (record_id,)).rowcount > 0

    def _get(self, record_id: str) -> NotificationRecord | None:
        row = self._db().execute("SELECT * FROM notifications WHERE id = ?", (record_id,)).fetchone()
        return None if row is None else self._from_row(row)

    def _get_by_rowid(self, db: sqlite3.Connection, rowid: int) -> NotificationRecord | None:
        row = db.execute("SELECT * FROM notifications WHERE rowid = ?", (rowid,)).fetchone()
        return None if row is None else self._from_row(row)

    def _query(self, query: Query) -> Page:
        where: list[str] = []
        params: list[Any] = []
        if query.user_id is not None:
            where.append(VISIBLE_TO_USER)
            params.append(query.user_id)
        if query.archive_user_id is not None:
            archived = "IN" if query.archived else "NOT IN"
            where.append(f"rowid {archived} (SELECT notification FROM notification_archive WHERE user_id = ?)")
            params.append(query.archive_user_id)
        if query.text and (match := _fts_query(query.text)):
            where.append("rowid IN (SELECT rowid FROM notifications_fts WHERE notifications_fts MATCH ?)")
            params.append(match)
        if query.channel:
            where.append("(channel = ? OR grp = ?)")
            params.extend([query.channel, query.channel])
        if query.origin_entity_id:
            where.append("origin_entity_id = ?")
            params.append(query.origin_entity_id)
        if query.status is not None:
            where.append("status = ?")
            params.append(query.status.value)
        if query.since is not None:
            where.append("time >= ?")
            params.append(query.since.timestamp())
        if query.until is not None:
            where.append("time < ?")
            params.append(query.until.timestamp())
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        order = "DESC" if query.newest_first else "ASC"
        db = self._db()
        total = None
        if query.with_counts:
            total = db.execute(f"SELECT count(*) FROM notifications {clause}", params).fetchone()[0]
        groups = None
        sort = f"time {order}, rowid {order}"
        if query.group_by_origin:
            if query.with_counts:
                groups = dict(
                    db.execute(
                        f"SELECT {ORIGIN_GROUP}, count(*) FROM notifications {clause} GROUP BY {ORIGIN_GROUP}", params
                    ).fetchall()
                )
            sort = f"origin_entity_id IS NULL, origin_entity_id, origin_kind, {ORIGIN_GROUP}, {sort}"
        rows = db.execute(
            f"SELECT * FROM notifications {clause} ORDER BY {sort} LIMIT ? OFFSET ?",
            [*params, query.limit, query.offset],
        ).fetchall()
        return Page(records=[self._from_row(row) for row in rows], total=total, groups=groups)

    def _facets(self, user_id: str | None) -> dict[str, list[dict[str, str | None]]]:
        where = f"WHERE {VISIBLE_TO_USER} AND" if user_id else "WHERE"
        params = [user_id] if user_id else []
        origins = (
            self._db()
            .execute(
                f"SELECT origin_entity_id, json_extract(origin, '$.name') FROM notifications {where} "
                "origin_entity_id IS NOT NULL GROUP BY origin_entity_id ORDER BY 2",
                params,
            )
            .fetchall()
        )
        return {"origins": [{"id": row[0], "name": row[1]} for row in origins]}

    def _purge(self, cutoff: float, max_entries: int) -> int:
        db = self._db()
        with db:
            removed = db.execute("DELETE FROM notifications WHERE time < ?", (cutoff,)).rowcount
            removed += db.execute(
                """DELETE FROM notifications WHERE rowid IN (
                       SELECT rowid FROM notifications ORDER BY time DESC, rowid DESC LIMIT -1 OFFSET ?)""",
                (max_entries,),
            ).rowcount
        return removed

    @staticmethod
    def _from_row(row: tuple[Any, ...]) -> NotificationRecord:
        (
            _rowid,
            record_id,
            time,
            source,
            channel,
            title,
            message,
            data,
            recipients,
            origin,
            _origin_kind,
            _origin_entity_id,
            context_id,
            status,
            error,
            group,
            inner_calls,
            source_ref,
            status_time,
            status_by,
            answers,
        ) = row
        return NotificationRecord(
            id=record_id,
            time=dt_util.utc_from_timestamp(time),
            source=source,
            channel=channel,
            title=title,
            message=message,
            data=None if data is None else json.loads(data),
            recipients=[recipient_from_dict(r) for r in json.loads(recipients)],
            origin=origin_from_dict(json.loads(origin)),
            context_id=context_id,
            status=Status(status),
            error=error,
            group=group,
            inner_calls=[call_from_dict(c) for c in json.loads(inner_calls)],
            source_ref=source_ref,
            status_time=None if status_time is None else dt_util.utc_from_timestamp(status_time),
            status_by=None if status_by is None else origin_from_dict(json.loads(status_by)),
            answers=[answer_from_dict(a) for a in json.loads(answers)],
        )
