import type { Localize } from "./localize";
import { notificationTag, spokenText } from "./media";
import { originLabel } from "./record";
import type { NotificationRecord } from "./types";

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

/** A spreadsheet reads a cell that starts like this as a formula, also after blanks it trims. */
const FORMULA = /^[\s]*[=+\-@]|^[\t\r\n]/;

/** The records as a file: JSON as the API returns them, CSV with one row per notification, separated as the spreadsheet
 * of a user who writes decimals with a comma expects: by semicolons. */
export function exportFile(
  format: ExportFormat,
  records: NotificationRecord[],
  userNames: Map<string, string>,
  localize: Localize,
  now: Date,
  separator: "," | ";",
): { name: string; type: string; content: string } {
  const two = (value: number) => String(value).padStart(2, "0");
  const stamp = `${now.getFullYear()}-${two(now.getMonth() + 1)}-${two(now.getDate())}-${two(now.getHours())}${two(now.getMinutes())}`;
  const name = `notification-journal-${stamp}.${format}`;
  if (format === "json") {
    const content = JSON.stringify({ exported: now.toISOString(), count: records.length, records }, null, 2);
    return { name, type: "application/json", content: `${content}\n` };
  }
  const quoted = (value: string) => cell(value, separator);
  const rows = [
    COLUMNS.join(separator),
    ...records.map((record) => row(record, userNames, localize).map(quoted).join(separator)),
  ];
  return { name, type: "text/csv;charset=utf-8", content: `﻿${rows.join("\r\n")}\r\n` };
}

/** Hand a file to the browser to save. */
export function download(file: { name: string; type: string; content: string }): void {
  const url = URL.createObjectURL(new Blob([file.content], { type: file.type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = file.name;
  link.hidden = true;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function row(record: NotificationRecord, userNames: Map<string, string>, localize: Localize): string[] {
  const by = (userId: string | null) => (userId && userNames.get(userId)) || localize("someone");
  return [
    record.time,
    record.status,
    record.title ?? "",
    spokenText(record) ?? record.message,
    record.source,
    record.channel,
    record.group ?? "",
    record.recipients.map((recipient) => recipient.name).join("; "),
    originLabel(record.origin, userNames, localize),
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
    record.status_by ? originLabel(record.status_by, userNames, localize) : "",
    record.resent_from ?? "",
    record.id,
  ];
}

function cell(value: string, separator: string): string {
  const text = FORMULA.test(value) ? `'${value}` : value;
  return /["\r\n]/.test(text) || text.includes(separator) ? `"${text.replaceAll('"', '""')}"` : text;
}
