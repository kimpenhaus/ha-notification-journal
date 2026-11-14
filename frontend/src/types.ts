export type Status = "sent" | "delivered" | "failed" | "dismissed" | "replaced";
export type RecipientKind = "person" | "entity" | "channel" | "everyone" | "speaker" | "chat";
export type OriginKind = "automation" | "script" | "user" | "system" | "unknown";

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
}

export interface Page {
  records: NotificationRecord[];
  total: number;
  groups?: Record<string, number>;
}

export type View = "time" | "origin";

export interface FacetOption {
  id: string;
  name: string;
  picture?: string | null;
}

export interface Facets {
  channels: FacetOption[];
  groups: FacetOption[];
  origins: FacetOption[];
  people: FacetOption[];
}

export type RecordEvent =
  { change: "added" | "updated"; record: NotificationRecord } | { change: "removed"; record_id: string };

export interface Filters {
  text: string;
  status: Status | "";
  origin: string;
  period: Period;
  newestFirst: boolean;
}

export type Period = "" | "day" | "week" | "month" | "quarter";

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
  locale?: { language: string; time_zone?: "local" | "server" };
  config: { time_zone: string };
  states: Record<string, HassEntityState>;
  dockedSidebar?: "docked" | "always_hidden" | "auto";
}
