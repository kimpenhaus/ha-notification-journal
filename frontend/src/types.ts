export type Status = "sent" | "delivered" | "failed" | "dismissed" | "replaced";
export type RecipientKind = "person" | "entity" | "channel" | "everyone" | "speaker" | "chat";
export type OriginKind = "automation" | "script" | "user" | "integration" | "system" | "unknown";

export interface Recipient {
  kind: RecipientKind;
  id: string;
  name: string;
  picture: string | null;
  user_id: string | null;
}

export interface Origin {
  kind: OriginKind;
  entity_id: string | null;
  name: string | null;
  trace_key: string | null;
  run_id: string | null;
  user_id: string | null;
  integration?: string | null;
  /** Rebuilt from the recorder on first setup. */
  imported?: boolean;
}

export interface Answer {
  action: string;
  time: string;
  user_id: string | null;
  reply_text: string | null;
}

export interface Call {
  channel: string;
  recipients: Recipient[];
  context_id: string;
}

export interface NotificationRecord {
  id: string;
  time: string;
  source: string;
  channel: string;
  title: string | null;
  message: string;
  data: Record<string, unknown> | null;
  recipients: Recipient[];
  origin: Origin;
  context_id: string;
  status: Status;
  error: string | null;
  group: string | null;
  inner_calls: Call[];
  trace_path: string | null;
  source_ref: string | null;
  status_time: string | null;
  status_by: Origin | null;
  answers: Answer[];
}

export interface Page {
  records: NotificationRecord[];
  total?: number;
  groups?: Record<string, number>;
}

export type View = "time" | "origin";

export interface FacetOption {
  /** The key of an origin: an automation or script, `integration.<domain>`, or a kind without a name. */
  id: string;
  name: string | null;
}

export interface Facets {
  origins: FacetOption[];
}

export type RecordEvent =
  | { change: "added" | "updated"; record: NotificationRecord }
  | { change: "removed"; record_id: string }
  | { change: "reload"; record_id: string };

export interface Filters {
  text: string;
  status: Status | "";
  origin: string;
  /** A time back from now, or a fixed span opened from the statistics. */
  period: Period | TimeRange;
  newestFirst: boolean;
}

export type Period = "" | "day" | "week" | "month" | "quarter";

export interface TimeRange {
  since: string;
  until: string;
  label: string;
}

export type StatisticsPeriod = "day" | "week" | "month" | "year";

export interface OriginStatistics {
  key: string;
  name: string | null;
  notifications: number;
  previous: number;
  with_buttons: number;
  answered: number;
  bursts: number;
  night: number;
}

export interface Statistics {
  period: StatisticsPeriod;
  start: string;
  end: string;
  has_older: boolean;
  /** Whether the counts reach back to the start of the period compared with. */
  comparable: boolean;
  kept_since: string | null;
  /** The sums over the origins, `previous` for the part of the period before compared with. */
  totals: Omit<OriginStatistics, "key" | "name">;
  buckets: { start: string; counts: Record<string, number> }[];
  /** Notifications per weekday (Monday first) and hour. */
  heatmap: number[][];
  origins: OriginStatistics[];
}

export interface StatisticsSelection {
  range: TimeRange;
  origin?: { key: string; name: string };
  /** When the oldest single notification still kept was sent; null when none are. */
  keptSince: string | null;
}

export interface HassEntityState {
  entity_id: string;
  state: string;
  attributes: Record<string, unknown>;
}

export interface HassConnection {
  sendMessagePromise<T>(message: Record<string, unknown>): Promise<T>;
  subscribeMessage<T>(callback: (message: T) => void, message: Record<string, unknown>): Promise<() => Promise<void>>;
}

export interface PanelInfo {
  title: string | null;
  url_path: string;
}

export interface HomeAssistant {
  connection: HassConnection;
  user?: { id: string; name: string; is_admin: boolean };
  language: string;
  locale?: { language: string; time_zone?: "local" | "server"; first_weekday?: string };
  config: { time_zone: string };
  states: Record<string, HassEntityState>;
  dockedSidebar?: "docked" | "always_hidden" | "auto";
}
