import type { Localize } from "./localize";

export interface Clock {
  language: string;
  timeZone: string | undefined;
}

const formatters = new Map<string, Intl.DateTimeFormat>();

function formatter(language: string, options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  const key = `${language}|${JSON.stringify(options)}`;
  let cached = formatters.get(key);
  if (!cached) {
    cached = new Intl.DateTimeFormat(language, options);
    formatters.set(key, cached);
  }
  return cached;
}

function parts(clock: Clock, date: Date): string {
  return formatter("en-CA", {
    timeZone: clock.timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

const dayKeys = new Map<string, string>();

export function dayKey(clock: Clock, iso: string): string {
  const key = `${clock.timeZone ?? ""}|${iso}`;
  let day = dayKeys.get(key);
  if (day === undefined) {
    if (dayKeys.size > 5000) dayKeys.clear();
    day = parts(clock, new Date(iso));
    dayKeys.set(key, day);
  }
  return day;
}

export function dayLabel(clock: Clock, localize: Localize, key: string, now = new Date()): string {
  if (key === parts(clock, now)) return localize("today");
  if (key === parts(clock, new Date(now.getTime() - 86_400_000))) return localize("yesterday");
  const [year, month, day] = key.split("-").map(Number);
  return formatter(clock.language, {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: year === now.getFullYear() ? undefined : "numeric",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(year, month - 1, day)));
}

export function timeText(clock: Clock, iso: string, seconds = false): string {
  return formatter(clock.language, {
    hour: "2-digit",
    minute: "2-digit",
    second: seconds ? "2-digit" : undefined,
    timeZone: clock.timeZone,
  }).format(new Date(iso));
}

export function shortDateTimeText(clock: Clock, iso: string): string {
  return formatter(clock.language, {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: clock.timeZone,
  }).format(new Date(iso));
}

export function dateTimeText(clock: Clock, iso: string): string {
  return formatter(clock.language, {
    dateStyle: "medium",
    timeStyle: "medium",
    timeZone: clock.timeZone,
  }).format(new Date(iso));
}

export function channelLabel(channel: string): string {
  return channel.replace(/^notify\./, "");
}

export function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  return words
    .slice(0, 2)
    .map((word) => word[0]!.toUpperCase())
    .join("");
}
