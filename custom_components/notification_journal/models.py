"""The record every source turns a notification into."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

EVERYONE: str = "*"
"""The user id under which a record counts for every user."""


class Status(StrEnum):
    """What is known about the delivery of a notification."""

    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    PARTIAL = "partial"
    """Some of the members of a group failed, the others were sent."""
    DISMISSED = "dismissed"
    REPLACED = "replaced"


class RecipientKind(StrEnum):
    """What a recipient stands for."""

    PERSON = "person"
    ENTITY = "entity"
    CHANNEL = "channel"
    EVERYONE = "everyone"
    SPEAKER = "speaker"
    CHAT = "chat"


class OriginKind(StrEnum):
    """What sent a notification."""

    AUTOMATION = "automation"
    SCRIPT = "script"
    USER = "user"
    INTEGRATION = "integration"
    SYSTEM = "system"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class Recipient:
    """A person, an entity or a channel a notification went to."""

    kind: RecipientKind
    id: str
    name: str
    picture: str | None = None
    user_id: str | None = None


@dataclass(slots=True)
class Origin:
    """The automation, script, user or integration that sent a notification."""

    kind: OriginKind
    entity_id: str | None = None
    name: str | None = None
    trace_key: str | None = None
    run_id: str | None = None
    user_id: str | None = None
    integration: str | None = None
    imported: bool = False
    """Rebuilt from the recorder on first setup: no trace, and no integration among the origins."""


@dataclass(slots=True)
class Call:
    """One call of a notify action, the call itself or one a group made for its members."""

    channel: str
    recipients: list[Recipient]
    context_id: str
    error: str | None = None


@dataclass(slots=True)
class Answer:
    """A button of an actionable notification that someone chose, with the text they typed if it asked for one."""

    action: str
    time: datetime
    user_id: str | None = None
    reply_text: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return the answer as plain data."""
        return {**asdict(self), "time": self.time.isoformat()}


@dataclass(slots=True)
class NotificationRecord:
    """A sent notification as the history keeps it."""

    id: str
    time: datetime
    source: str
    channel: str
    title: str | None
    message: str
    data: dict[str, Any] | None
    recipients: list[Recipient]
    origin: Origin
    context_id: str
    status: Status = Status.SENT
    error: str | None = None
    group: str | None = None
    inner_calls: list[Call] = field(default_factory=list)
    source_ref: str | None = None
    status_time: datetime | None = None
    status_by: Origin | None = None
    answers: list[Answer] = field(default_factory=list)

    @property
    def all_recipients(self) -> list[Recipient]:
        """The recipients, those the calls of a group reached included."""
        return [*self.recipients, *(r for call in self.inner_calls for r in call.recipients)]

    @property
    def user_ids(self) -> set[str]:
        """The users among the recipients, the calls of a group included; EVERYONE for the bell and announcements."""
        recipients = self.all_recipients
        users = {r.user_id for r in recipients if r.user_id}
        if any(r.kind in (RecipientKind.EVERYONE, RecipientKind.SPEAKER) for r in recipients):
            users.add(EVERYONE)
        return users

    def visible_to(self, user_id: str) -> bool:
        """Return whether a user who sees only their own notifications sees this record."""
        users = self.user_ids
        return user_id in users or EVERYONE in users

    def as_dict(self) -> dict[str, Any]:
        """Return the record as plain data."""
        result = asdict(self)
        result["time"] = self.time.isoformat()
        result["status_time"] = self.status_time.isoformat() if self.status_time else None
        result["answers"] = [answer.as_dict() for answer in self.answers]
        return result


def recipient_from_dict(data: dict[str, Any]) -> Recipient:
    """Rebuild a recipient from plain data."""
    return Recipient(**{**data, "kind": RecipientKind(data["kind"])})


def origin_from_dict(data: dict[str, Any]) -> Origin:
    """Rebuild an origin from plain data."""
    return Origin(**{**data, "kind": OriginKind(data["kind"])})


def answer_from_dict(data: dict[str, Any]) -> Answer:
    """Rebuild an answer from plain data."""
    return Answer(**{**data, "time": datetime.fromisoformat(data["time"])})


def call_from_dict(data: dict[str, Any]) -> Call:
    """Rebuild a call from plain data."""
    return Call(
        channel=data["channel"],
        recipients=[recipient_from_dict(r) for r in data["recipients"]],
        context_id=data["context_id"],
        error=data.get("error"),
    )
