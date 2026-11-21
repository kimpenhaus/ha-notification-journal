import { notificationTag } from "./media";
import type { NotificationRecord, Origin } from "./types";

export type ExportFormat = "csv" | "json";

const COLUMNS = [
  "time",
  "status",
  "title",
  "message",
  "source",
  "channel",
  "group",
  "recipients",
  "origin",
  "origin_entity",
  "tag",
  "error",
  "failed_calls",
  "answers",
  "status_time",
  "status_by",
  "resent_from",
  "id",
] as const;

/** A spreadsheet reads a cell that starts like this as a formula. */
const FORMULA = /^[=+\-@\t\r]/;

/** The records as a file: JSON as the API returns them, CSV with one row per notification. */
export function exportFile(
  format: ExportFormat,
  records: NotificationRecord[],
  userNames: Map<string, string>,
  now: Date,
): { name: string; type: string; content: string } {
  const stamp = now.toISOString().slice(0, 16).replace("T", "-").replace(":", "");
  const name = `notification-journal-${stamp}.${format}`;
  if (format === "json") {
    const content = JSON.stringify({ exported: now.toISOString(), count: records.length, records }, null, 2);
    return { name, type: "application/json", content: `${content}\n` };
  }
  const rows = [COLUMNS.join(","), ...records.map((record) => row(record, userNames).map(cell).join(","))];
  return { name, type: "text/csv;charset=utf-8", content: `﻿${rows.join("\r\n")}\r\n` };
}

/** Hand a file to the browser to save. */
export function download(file: { name: string; type: string; content: string }): void {
  const url = URL.createObjectURL(new Blob([file.content], { type: file.type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = file.name;
  link.click();
  URL.revokeObjectURL(url);
}

function row(record: NotificationRecord, userNames: Map<string, string>): string[] {
  const by = (userId: string | null) => (userId && userNames.get(userId)) || userId || "";
  return [
    record.time,
    record.status,
    record.title ?? "",
    record.message,
    record.source,
    record.channel,
    record.group ?? "",
    record.recipients.map((recipient) => recipient.name).join("; "),
    originText(record.origin, by),
    record.origin.entity_id ?? "",
    notificationTag(record) ?? "",
    record.error ?? "",
    record.inner_calls
      .filter((call) => call.error)
      .map((call) => `${call.channel}: ${call.error}`)
      .join("; "),
    record.answers
      .map((answer) => {
        const reply = answer.reply_text ? ` "${answer.reply_text}"` : "";
        return `${answer.action}${reply} (${by(answer.user_id)}, ${answer.time})`;
      })
      .join("; "),
    record.status_time ?? "",
    record.status_by ? originText(record.status_by, by) : "",
    record.resent_from ?? "",
    record.id,
  ];
}

function originText(origin: Origin, by: (userId: string | null) => string): string {
  if (origin.kind === "user") return by(origin.user_id) || "user";
  return origin.name ?? origin.entity_id ?? origin.integration ?? origin.kind;
}

function cell(value: string): string {
  const text = FORMULA.test(value) ? `'${value}` : value;
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}
