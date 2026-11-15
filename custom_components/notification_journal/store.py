"""Keep the recorded notifications in an SQLite database of their own."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from homeassistant.util import dt as dt_util

from .const import INTEGRATION_KEY_PREFIX
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
from .statistics import (
    ALL,
    BURST_SIZE,
    BURST_WINDOW,
    COUNTS_SCHEMA,
    UPSERT_COUNTS,
    BurstWindow,
    Counts,
    contributions,
    counts_of,
    difference,
    group_key,
    has_buttons,
    slot_of,
    view_keys,
    year_start,
)

_LOGGER = logging.getLogger(__name__)

SCHEMA_VERSION = 5
VISIBLE_TO_USER = f"rowid IN (SELECT notification FROM notification_users WHERE user_id IN (?, '{EVERYONE}'))"
BACKUP_PAUSE_LIMIT = 1800
MIGRATION_COPY_DAYS = 7
ORIGIN_KEY_OF_ROW = (
    f"coalesce(origin_entity_id, '{INTEGRATION_KEY_PREFIX}' || json_extract(origin, '$.integration'), origin_kind)"
)
"""The origin key (`statistics.group_key`) of a stored row, to fill `origin_key` in migration 5."""

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
    answers TEXT NOT NULL DEFAULT '[]',
    origin_key TEXT NOT NULL DEFAULT '',
    burst INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS notifications_time ON notifications (time);
CREATE INDEX IF NOT EXISTS notifications_origin ON notifications (origin_entity_id);
CREATE INDEX IF NOT EXISTS notifications_origin_key ON notifications (origin_key, time);
CREATE TABLE IF NOT EXISTS notification_users (
    notification INTEGER NOT NULL REFERENCES notifications (rowid) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    burst INTEGER NOT NULL DEFAULT 0,
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
""" + "".join(f"{statement};\n" for statement in COUNTS_SCHEMA)


def _fill_counts(db: sqlite3.Connection) -> None:
    """Count the notifications already stored, in order of time, as they are counted when they arrive."""
    users: defaultdict[int, set[str]] = defaultdict(set)
    for rowid, user_id in db.execute("SELECT notification, user_id FROM notification_users"):
        users[rowid].add(user_id)
    window = BurstWindow()
    totals: defaultdict[tuple[str, int, str], list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    starts: list[tuple[int]] = []
    user_starts: list[tuple[int, str]] = []
    rows = db.execute("SELECT rowid, time, data, origin_key, answers FROM notifications ORDER BY time, rowid")
    for rowid, sent, data, key, answers in rows.fetchall():
        bursts = {ALL: window.add(ALL, key, sent)}
        for user_id in sorted(users[rowid]):
            burst = window.add(user_id, key, sent)
            if burst:
                user_starts.append((rowid, user_id))
            bursts[user_id] = burst
        if bursts[ALL]:
            starts.append((rowid,))
        views = {view: bursts[view] for view in (ALL, *view_keys(users[rowid]))}
        buttons = has_buttons(None if data is None else json.loads(data))
        stored_answers = [answer_from_dict(a) for a in json.loads(answers)]
        for user_id, counts in contributions(views, buttons, stored_answers).items():
            total = totals[(user_id, slot_of(sent), key)]
            for index, value in enumerate(counts):
                total[index] += value
    db.executemany("UPDATE notifications SET burst = 1 WHERE rowid = ?", starts)
    db.executemany("UPDATE notification_users SET burst = 1 WHERE notification = ? AND user_id = ?", user_starts)
    db.executemany(UPSERT_COUNTS, [(*key, *values) for key, values in totals.items()])


Migration = str | Callable[[sqlite3.Connection], None]

MIGRATIONS: dict[int, tuple[Migration, ...]] = {
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
    5: (
        "ALTER TABLE notifications ADD COLUMN origin_key TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE notifications ADD COLUMN burst INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE notification_users ADD COLUMN burst INTEGER NOT NULL DEFAULT 0",
        f"UPDATE notifications SET origin_key = {ORIGIN_KEY_OF_ROW}",
        "CREATE INDEX notifications_origin_key ON notifications (origin_key, time)",
        *COUNTS_SCHEMA,
        _fill_counts,
    ),
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
    origin: str | None = None
    """The key of an origin (`origin_key`): an automation or script, `integration.<domain>`, or a kind."""
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


def _views(burst: int | bool, users: dict[str, bool]) -> dict[str, bool]:
    """Return the views a notification counts for, with whether it starts a burst in each."""
    return {ALL: bool(burst), **{view: users[view] for view in view_keys(users)}}


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
        """Return the origins that sent notifications, by key, limited to a user's records if given.

        Each comes with the name stored with its newest notification (SQLite takes the bare column from the row of max).
        """
        return await self._run(self._facets, user_id)

    async def async_statistics(
        self, user_id: str | None, ranges: list[tuple[float, float]]
    ) -> tuple[list[tuple[int, str, int, int, int, int]], int | None, float | None]:
        """Return the counts within the ranges, for administrators or a user's view, by quarter hour and origin.

        Also return the oldest quarter hour counted for that view and the time of the oldest record kept.
        """
        return await self._run(self._statistics, user_id, ranges)

    async def async_stored_names(self, keys: list[str]) -> dict[str, str]:
        """Return the names stored with the newest notification of each origin key."""
        return await self._run(self._stored_names, keys)

    async def async_get(self, record_id: str) -> NotificationRecord | None:
        """Return one record."""
        return await self._run(self._get, record_id)

    async def async_query(self, query: Query) -> Page:
        """Return the records that match a query."""
        return await self._run(self._query, query)

    async def async_purge(self, retention_days: int, max_entries: int, statistics_years: int) -> int:
        """Delete records older than the retention and beyond the maximum number; return how many.

        The counts are kept for statistics_years calendar years, and never shorter than the records.
        """
        cutoff = (dt_util.utcnow() - timedelta(days=retention_days)).timestamp()
        counts_cutoff = min(cutoff, year_start(dt_util.now(), statistics_years).timestamp())
        removed = await self._run(self._purge, cutoff, max_entries, counts_cutoff)
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
        self._remove_migration_copies()

    def _remove_migration_copies(self) -> None:
        """Remove the copies made before migrations: all but the latest, and that one after MIGRATION_COPY_DAYS."""
        database = Path(self._path)
        name = re.compile(rf"{re.escape(database.name)}\.bak-v(\d+)")
        try:
            copies = sorted(
                (int(match[1]), path) for path in database.parent.iterdir() if (match := name.fullmatch(path.name))
            )
        except OSError as error:
            _LOGGER.warning("Could not look for old copies of %s: %s", database, error)
            return
        expired = time.time() - MIGRATION_COPY_DAYS * 86400
        for index, (_, copy) in enumerate(copies):
            try:
                if index == len(copies) - 1 and copy.stat().st_mtime > expired:
                    continue
                copy.unlink()
            except OSError as error:
                _LOGGER.warning("Could not remove %s: %s", copy, error)
                continue
            _LOGGER.debug("Removed %s, a copy made before a schema migration", copy)

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
                    if callable(statement):
                        statement(connection)
                    else:
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
        key = group_key(record.origin)
        sent = record.time.timestamp()
        with db:
            burst = self._starts_burst(db, ALL, key, sent)
            cursor = db.execute(
                """INSERT INTO notifications (id, time, source, channel, title, message, data, recipients, origin,
                       origin_kind, origin_entity_id, context_id, status, error, grp, inner_calls, source_ref,
                       status_time, status_by, answers, origin_key, burst)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.id,
                    sent,
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
                    key,
                    int(burst),
                ),
            )
            rowid = cursor.lastrowid
            users = self._index(db, rowid, record, key)
            self._count(db, sent, key, counts_of(record, _views(burst, users)))

    def _append_call(self, record_id: str, call: Call) -> None:
        db = self._db()
        with db:
            row = db.execute("SELECT rowid, burst, origin_key FROM notifications WHERE id = ?", (record_id,)).fetchone()
            if row is None:
                return
            rowid, burst, key = row
            before = self._get_by_rowid(db, rowid)
            users_before = self._user_bursts(db, rowid)
            db.execute(
                "UPDATE notifications SET inner_calls = json_insert(inner_calls, '$[#]', json(?)) WHERE rowid = ?",
                (json.dumps(asdict(call)), rowid),
            )
            record = self._get_by_rowid(db, rowid)
            if before is not None and record is not None:
                users = self._index(db, rowid, record, key)
                changes = difference(
                    counts_of(before, _views(burst, users_before)), counts_of(record, _views(burst, users))
                )
                self._count(db, record.time.timestamp(), key, changes)

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
            "SELECT rowid, id, burst, origin_key FROM notifications WHERE source = ? AND EXISTS "
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
        rowid, record_id, burst, key = row
        with db:
            before = self._get_by_rowid(db, rowid)
            db.execute(
                "UPDATE notifications SET answers = json_insert(answers, '$[#]', json(?)) WHERE rowid = ?",
                (json.dumps(answer.as_dict()), rowid),
            )
            if before is not None:
                views = _views(burst, self._user_bursts(db, rowid))
                after = replace(before, answers=[*before.answers, answer])
                self._count(
                    db, before.time.timestamp(), key, difference(counts_of(before, views), counts_of(after, views))
                )
        return record_id

    def _open_records(self, source: str) -> dict[str, tuple[str, datetime]]:
        rows = self._db().execute(
            "SELECT source_ref, id, time FROM notifications WHERE source = ? AND source_ref IS NOT NULL AND status = ?",
            (source, Status.SENT.value),
        )
        return {ref: (record_id, dt_util.utc_from_timestamp(time)) for ref, record_id, time in rows}

    @staticmethod
    def _count(db: sqlite3.Connection, sent: float, key: str, changes: dict[str, Counts]) -> None:
        slot = slot_of(sent)
        db.executemany(UPSERT_COUNTS, [(user_id, slot, key, *counts) for user_id, counts in changes.items()])

    @staticmethod
    def _starts_burst(db: sqlite3.Connection, view: str, key: str, sent: float) -> bool:
        """Return whether a notification not yet counted in a view starts a burst there (`BurstWindow`)."""
        if view == ALL:
            query = "SELECT count(*) FROM notifications WHERE origin_key = ? AND time > ? AND time <= ?"
            params: tuple[Any, ...] = (key, sent - BURST_WINDOW, sent)
        else:
            query = (
                "SELECT count(*) FROM notification_users u JOIN notifications n ON n.rowid = u.notification "
                "WHERE u.user_id = ? AND n.origin_key = ? AND n.time > ? AND n.time <= ?"
            )
            params = (view, key, sent - BURST_WINDOW, sent)
        return db.execute(query, params).fetchone()[0] + 1 == BURST_SIZE

    @staticmethod
    def _user_bursts(db: sqlite3.Connection, rowid: int) -> dict[str, bool]:
        rows = db.execute("SELECT user_id, burst FROM notification_users WHERE notification = ?", (rowid,))
        return {user_id: bool(burst) for user_id, burst in rows}

    def _index(
        self, db: sqlite3.Connection, rowid: int | None, record: NotificationRecord, key: str
    ) -> dict[str, bool]:
        """Add the users a record reached and index its text; return its users and whether it starts a burst there."""
        users = self._user_bursts(db, rowid) if rowid is not None else {}
        sent = record.time.timestamp()
        for user_id in sorted(record.user_ids - users.keys()):
            users[user_id] = self._starts_burst(db, user_id, key, sent)
            db.execute(
                "INSERT INTO notification_users (notification, user_id, burst) VALUES (?, ?, ?)",
                (rowid, user_id, int(users[user_id])),
            )
        db.execute("DELETE FROM notifications_fts WHERE rowid = ?", (rowid,))
        db.execute(
            "INSERT INTO notifications_fts (rowid, title, message, channel, people, origin) VALUES (?, ?, ?, ?, ?, ?)",
            (rowid, record.title or "", record.message, record.channel, _people(record), record.origin.name or ""),
        )
        return users

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
        if query.origin:
            where.append("origin_key = ?")
            params.append(query.origin)
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
                        f"SELECT origin_key, count(*) FROM notifications {clause} GROUP BY origin_key", params
                    ).fetchall()
                )
            sort = f"origin_entity_id IS NULL, origin_entity_id, origin_kind, origin_key, {sort}"
        rows = db.execute(
            f"SELECT * FROM notifications {clause} ORDER BY {sort} LIMIT ? OFFSET ?",
            [*params, query.limit, query.offset],
        ).fetchall()
        return Page(records=[self._from_row(row) for row in rows], total=total, groups=groups)

    def _facets(self, user_id: str | None) -> dict[str, list[dict[str, str | None]]]:
        where = f"WHERE {VISIBLE_TO_USER}" if user_id else ""
        params = [user_id] if user_id else []
        origins = (
            self._db()
            .execute(
                f"SELECT origin_key, json_extract(origin, '$.name'), max(time) FROM notifications {where} "
                "GROUP BY origin_key",
                params,
            )
            .fetchall()
        )
        return {"origins": [{"id": row[0], "name": row[1]} for row in origins]}

    def _statistics(
        self, user_id: str | None, ranges: list[tuple[float, float]]
    ) -> tuple[list[tuple[int, str, int, int, int, int]], int | None, float | None]:
        db = self._db()
        users = [ALL] if user_id is None else [user_id, EVERYONE]
        view = f"user_id IN ({', '.join('?' * len(users))})"
        within = " OR ".join("(slot >= ? AND slot < ?)" for _ in ranges)
        rows = db.execute(
            "SELECT slot, origin, sum(notifications), sum(with_buttons), sum(answered), sum(bursts) "
            f"FROM notification_counts WHERE {view} AND ({within}) GROUP BY slot, origin",
            [*users, *(bound for span in ranges for bound in span)],
        ).fetchall()
        oldest = db.execute(f"SELECT min(slot) FROM notification_counts WHERE {view}", users).fetchone()[0]
        kept = db.execute("SELECT min(time) FROM notifications").fetchone()[0]
        return rows, oldest, kept

    def _stored_names(self, keys: list[str]) -> dict[str, str]:
        rows = self._db().execute(
            "SELECT origin_key, json_extract(origin, '$.name'), max(time) FROM notifications "
            f"WHERE origin_key IN ({', '.join('?' * len(keys))}) GROUP BY origin_key",
            keys,
        )
        return {key: name for key, name, _ in rows if name}

    def _purge(self, cutoff: float, max_entries: int, counts_cutoff: float) -> int:
        db = self._db()
        with db:
            db.execute("DELETE FROM notification_counts WHERE slot < ?", (counts_cutoff,))
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
            _origin_key,
            _burst,
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
