import { css, html, LitElement, nothing, type PropertyValues, type TemplateResult } from "lit";
import { repeat } from "lit/directives/repeat.js";

import { type Clock, dayKey, dayLabel, formatter, zoneName } from "./format";
import {
  icon,
  mdiArchiveArrowDownOutline,
  mdiArchiveArrowUpOutline,
  mdiArchiveOutline,
  mdiArrowLeft,
  mdiCalendarClockOutline,
  mdiChartBar,
  mdiCheckboxMultipleMarkedOutline,
  mdiChevronDown,
  mdiClose,
  mdiFilterRemoveOutline,
  mdiInboxOutline,
  mdiMagnify,
  mdiMenu,
  mdiMessageBadgeOutline,
  mdiRefresh,
  mdiRobotOutline,
  mdiSelectAll,
  mdiSelectRemove,
  mdiSortClockAscendingOutline,
  mdiSortClockDescendingOutline,
  mdiTagOutline,
  mdiUnfoldLessHorizontal,
  mdiUnfoldMoreHorizontal,
} from "./icons";
import { countText, type Localize, localizer } from "./localize";
import { type Signer, signPath } from "./media";
import { originGlyph, originName } from "./record";
import type { NotificationJournalStatistics } from "./statistics";
import "./statistics";
import { controlStyles } from "./styles";
import type {
  Day,
  Facets,
  Filters,
  HassConnection,
  HomeAssistant,
  NotificationRecord,
  Page,
  PanelInfo,
  Period,
  RecordEvent,
  StatisticsSelection,
  Status,
  View,
} from "./types";
import { errorMessage, store, stored } from "./util";

const PAGE_SIZE = 50;
const DAY_PAGE_SIZE = 200;
const ARCHIVE_BATCH = 200;
const SEARCH_DELAY = 300;
const SUBSCRIBE_RETRY = 5000;
const PERIODS: Record<Exclude<Period, "">, number> = { day: 1, week: 7, month: 30, quarter: 90 };
const STATUSES: Status[] = ["sent", "failed", "partial", "dismissed", "replaced"];
const DEFAULT_FILTERS: Filters = {
  text: "",
  status: "",
  origin: "",
  tag: "",
  period: "",
  newestFirst: true,
};
const VIEW_KEY = "notification_journal.view";
const ORDER_KEY = "notification_journal.newest_first";

type Item =
  | { day: string; collapsed: boolean; count?: number }
  | { group: string; record: NotificationRecord }
  | { record: NotificationRecord }
  | { waiting: string };

/** The key of an origin's group, the same as `origin_key` in the store. */
function groupKey(record: NotificationRecord): string {
  const origin = record.origin;
  return origin.entity_id ?? (origin.integration ? `integration.${origin.integration}` : origin.kind);
}

function compare(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}

function originRank(record: NotificationRecord): string {
  return record.origin.entity_id ? `0${record.origin.entity_id}` : `1${record.origin.kind} ${groupKey(record)}`;
}

function sameMap(left: Map<string, string>, right: Map<string, string>): boolean {
  if (left.size !== right.size) return false;
  for (const [key, value] of left) if (right.get(key) !== value) return false;
  return true;
}

function errorCode(error: unknown): string | undefined {
  return typeof error === "object" && error && "code" in error ? String(error.code) : undefined;
}

export class NotificationJournalPanel extends LitElement {
  static override properties = {
    narrow: { type: Boolean },
    panel: { attribute: false },
    _records: { state: true },
    _total: { state: true },
    _facets: { state: true },
    _filters: { state: true },
    _search: { state: true },
    _loading: { state: true },
    _error: { state: true },
    _pending: { state: true },
    _view: { state: true },
    _groups: { state: true },
    _folded: { state: true },
    _days: { state: true },
    _dayLoads: { state: true },
    _notice: { state: true },
    _archived: { state: true },
    _selecting: { state: true },
    _selected: { state: true },
    _screen: { state: true },
  };

  declare narrow: boolean;
  declare panel: PanelInfo | undefined;
  declare _records: NotificationRecord[];
  declare _total: number;
  declare _facets: Facets;
  declare _filters: Filters;
  declare _search: string;
  declare _loading: boolean;
  declare _error: string | undefined;
  declare _pending: number;
  declare _view: View;
  declare _groups: Record<string, number>;
  declare _folded: Map<string, boolean>;
  /** Every day of the plain timeline; its notifications load when a day opens. Unset while the list pages. */
  declare _days: Day[] | undefined;
  /** Days whose notifications are loading or failed to load, with the text shown in their place. */
  declare _dayLoads: Map<string, string>;
  private _grouped?: { records: NotificationRecord[]; days: Map<string, NotificationRecord[]> };
  private _open: "all" | "none" | "later" | `day-${string}` = "later";
  private _foldedFor = "";
  declare _notice: string | undefined;
  declare _archived: boolean;
  declare _selecting: boolean;
  declare _selected: Set<string>;
  declare _screen: "list" | "statistics";

  private _hass?: HomeAssistant;
  private _request = 0;
  private _unsubscribe?: Promise<() => Promise<void>>;
  private _connection?: HassConnection;
  private _subscribeTimer?: number;
  private _searchTimer?: number;
  private _facetsTimer?: number;
  private _daysTimer?: number;
  private _statisticsTimer?: number;
  /** Names of origins the statistics opened, which the filter may not offer once their notifications are gone. */
  private _originNames = new Map<string, string>();
  private _keptSince: string | null = null;
  private _observer?: IntersectionObserver;
  private _localizer?: { language: string; localize: Localize };
  private _clockCache?: Clock;
  private _lookupStates?: HomeAssistant["states"];
  private _names = new Map<string, string>();
  private _icons = new Map<string, string>();

  constructor() {
    super();
    this.narrow = false;
    this._records = [];
    this._total = 0;
    this._facets = { origins: [] };
    this._filters = { ...DEFAULT_FILTERS, newestFirst: stored(ORDER_KEY) !== "false" };
    this._view = stored(VIEW_KEY) === "origin" ? "origin" : "time";
    this._groups = {};
    this._folded = new Map();
    this._dayLoads = new Map();
    this._archived = false;
    this._selecting = false;
    this._selected = new Set();
    this._screen = "list";
    this._search = "";
    this._loading = false;
    this._pending = 0;
  }

  private readonly _sign: Signer = (path) => signPath(this._hass!.connection, path);
  /** The subscription ended with the old connection, and what was sent meanwhile never arrived. */
  private readonly _reconnected = () => {
    this._unsubscribeNow();
    this._subscribe(true);
  };
  private readonly _resend = (recordId: string) =>
    this._hass!.connection.sendMessagePromise({ type: "notification_journal/resend", record_id: recordId });

  get hass(): HomeAssistant | undefined {
    return this._hass;
  }

  set hass(hass: HomeAssistant) {
    const previous = this._hass;
    this._hass = hass;
    if (
      !previous ||
      previous.language !== hass.language ||
      previous.user?.is_admin !== hass.user?.is_admin ||
      previous.dockedSidebar !== hass.dockedSidebar
    ) {
      this.requestUpdate();
    }
    if (!previous && this.isConnected) this._start();
    else if (this._connection && previous?.connection !== hass.connection) this._reconnected();
  }

  override connectedCallback(): void {
    super.connectedCallback();
    if (this._hass) this._start();
  }

  override disconnectedCallback(): void {
    super.disconnectedCallback();
    this._stop();
  }

  private get _localize(): Localize {
    const language = this._hass?.locale?.language ?? this._hass?.language ?? "en";
    if (this._localizer?.language !== language) this._localizer = { language, localize: localizer(language) };
    return this._localizer.localize;
  }

  private get _clock(): Clock {
    const hass = this._hass;
    const language = hass?.locale?.language ?? hass?.language ?? "en";
    const timeZone = hass?.locale?.time_zone === "local" ? undefined : hass?.config.time_zone;
    if (this._clockCache?.language !== language || this._clockCache.timeZone !== timeZone) {
      this._clockCache = { language, timeZone };
    }
    return this._clockCache;
  }

  private get _admin(): boolean {
    return Boolean(this._hass?.user?.is_admin);
  }

  private _start(): void {
    if (this._unsubscribe || !this._hass) return;
    this._subscribe(false);
    this._refresh();
  }

  private _subscribe(catchUp: boolean): void {
    window.clearTimeout(this._subscribeTimer);
    const connection = this._hass!.connection;
    if (this._connection !== connection) {
      this._connection?.removeEventListener("ready", this._reconnected);
      connection.addEventListener("ready", this._reconnected);
      this._connection = connection;
    }
    const subscription = connection.subscribeMessage<RecordEvent>(
      (event) => this._received(event),
      { type: "notification_journal/subscribe" },
      { resubscribe: false },
    );
    this._unsubscribe = subscription;
    subscription.then(
      () => {
        if (catchUp && this._unsubscribe === subscription) this._catchUp();
      },
      () => {
        if (this._unsubscribe !== subscription) return;
        this._unsubscribe = undefined;
        this._subscribeTimer = window.setTimeout(() => this._subscribe(true), SUBSCRIBE_RETRY);
      },
    );
  }

  private _catchUp(): void {
    this._refresh();
    if (this._screen === "statistics") void this._statistics?.refresh();
  }

  private _unsubscribeNow(): void {
    const unsubscribe = this._unsubscribe;
    this._unsubscribe = undefined;
    unsubscribe?.then((stop) => stop()).catch(() => undefined);
  }

  private _stop(): void {
    this._unsubscribeNow();
    this._connection?.removeEventListener("ready", this._reconnected);
    this._connection = undefined;
    window.clearTimeout(this._subscribeTimer);
    this._observer?.disconnect();
    this._observer = undefined;
    window.clearTimeout(this._searchTimer);
    window.clearTimeout(this._facetsTimer);
    window.clearTimeout(this._statisticsTimer);
    window.clearTimeout(this._daysTimer);
  }

  private _query(): Record<string, unknown> {
    const filters = this._filters;
    const query: Record<string, unknown> = { newest_first: filters.newestFirst };
    if (filters.text.trim()) query.text = filters.text.trim();
    if (filters.status) query.status = filters.status;
    if (filters.origin) query.origin = filters.origin;
    if (filters.tag) query.tag = filters.tag;
    if (this._archived) query.archived = true;
    if (this._view === "origin") query.group_by = "origin";
    if (typeof filters.period === "object") {
      query.since = filters.period.since;
      query.until = filters.period.until;
    } else if (filters.period) {
      query.since = new Date(Date.now() - PERIODS[filters.period] * 86_400_000).toISOString();
    }
    return query;
  }

  private async _load(more = false): Promise<void> {
    if (!this._hass) return;
    const request = ++this._request;
    this._loading = true;
    try {
      const withDays = this._byDay && !more;
      const page = await this._list({
        limit: PAGE_SIZE,
        offset: more ? this._records.length : 0,
        ...(withDays ? this._dayQuery : {}),
      });
      if (request !== this._request) return;
      if (more) {
        if (!this._append(page.records)) {
          // A record that arrived meanwhile shifted the offsets; what the server counts is already loaded.
          this._total = this._records.length;
          return;
        }
      } else {
        this._records = page.records;
        this._pending = 0;
        this._days = withDays ? (page.days ?? []) : undefined;
        this._dayLoads = new Map();
      }
      if (page.total !== undefined) this._total = page.total;
      if (page.groups !== undefined || !more) this._groups = page.groups ?? {};
      this._refold();
      this._error = undefined;
    } catch (error) {
      if (request !== this._request) return;
      const code = errorCode(error);
      this._error =
        code === "not_loaded" || code === "unauthorized"
          ? this._localize(code)
          : this._localize("load_failed", { message: errorMessage(error) });
    } finally {
      if (request === this._request) this._loading = false;
    }
  }

  private async _loadFacets(): Promise<void> {
    try {
      this._facets = await this._hass!.connection.sendMessagePromise<Facets>({ type: "notification_journal/facets" });
    } catch {
      // The list reports the error.
    }
  }

  private _received(event: RecordEvent): void {
    if (event.change !== "removed" && this._screen === "statistics") {
      window.clearTimeout(this._statisticsTimer);
      this._statisticsTimer = window.setTimeout(() => void this._statistics?.refresh(), 2000);
    }
    if (event.change === "removed") {
      this._removed(event.record_id);
      return;
    }
    if (event.change === "reload") {
      this._refresh();
      return;
    }
    const { change, record } = event;
    const index = this._records.findIndex((known) => known.id === record.id);
    if (index >= 0) {
      this._records = this._records.map((known, position) => (position === index ? record : known));
    } else if (change === "added" && !this._archived) {
      if (this._days) {
        this._count([record], 1);
        this._append([record]);
      } else if (this._unfiltered && this._complete) {
        const first = this._records[0];
        this._records = [record, ...this._records];
        this._total += 1;
        const inPlace = this._view === "time" && this._filters.newestFirst && (!first || record.time >= first.time);
        if (!inPlace) this._arrange();
      } else {
        this._pending += 1;
      }
      window.clearTimeout(this._facetsTimer);
      this._facetsTimer = window.setTimeout(() => void this._loadFacets(), 2000);
    }
  }

  private get _statistics(): NotificationJournalStatistics | null {
    return this.renderRoot.querySelector("notification-journal-statistics");
  }

  private _showStatistics(show: boolean): void {
    this._screen = show ? "statistics" : "list";
    this._endSelection();
    this.renderRoot.querySelector(".content")?.scrollTo({ top: 0 });
  }

  /** Open the list on what a bar or an origin of the statistics stands for. */
  private _openSelection({ range, origin, keptSince }: StatisticsSelection): void {
    if (origin) this._originNames.set(origin.key, origin.name);
    this._keptSince = keptSince;
    this._screen = "list";
    this._archived = false;
    this._search = "";
    window.clearTimeout(this._searchTimer);
    this._set({ ...DEFAULT_FILTERS, newestFirst: this._filters.newestFirst, origin: origin?.key ?? "", period: range });
  }

  private _removed(recordId: string): void {
    this._drop([recordId]);
  }

  private _drop(recordIds: string[]): void {
    const ids = new Set(recordIds);
    const gone = this._records.filter((known) => ids.has(known.id));
    if (!gone.length) {
      if (this._days) this._refreshDays();
      return;
    }
    this._records = this._records.filter((known) => !ids.has(known.id));
    if (this._days) this._count(gone, -1);
    else this._total = Math.max(0, this._total - gone.length);
    const groups = { ...this._groups };
    for (const record of gone) if (groups[groupKey(record)]) groups[groupKey(record)] -= 1;
    this._groups = groups;
    this._settle();
  }

  private async _archive(): Promise<void> {
    const ids = [...this._selected];
    if (!ids.length) return;
    this._notice = undefined;
    try {
      for (let start = 0; start < ids.length; start += ARCHIVE_BATCH) {
        await this._hass!.connection.sendMessagePromise({
          type: "notification_journal/archive",
          record_ids: ids.slice(start, start + ARCHIVE_BATCH),
          archived: !this._archived,
        });
      }
      this._drop(ids);
      this._endSelection();
    } catch (error) {
      this._notice = this._localize("archive_failed", { message: errorMessage(error) });
    }
  }

  private _select(recordId: string): void {
    const selected = new Set(this._selected);
    if (!selected.delete(recordId)) selected.add(recordId);
    this._selected = selected;
  }

  private _selectAll(): void {
    const shown = this._shown();
    this._selected = this._selected.size === shown.length ? new Set() : new Set(shown.map((record) => record.id));
  }

  /** The records on screen: by day, only those of open days loaded whole. */
  private _shown(): NotificationRecord[] {
    if (!this._days) return this._records;
    const byDay = this._recordsByDay();
    return this._days
      .filter((day) => !this._isCollapsed(`day-${day.day}`) && this._loaded(day))
      .flatMap((day) => byDay.get(day.day) ?? []);
  }

  private _endSelection(): void {
    this._selecting = false;
    this._selected = new Set();
  }

  private _setArchived(archived: boolean): void {
    if (archived === this._archived) return;
    this._archived = archived;
    this._endSelection();
    this.renderRoot.querySelector(".content")?.scrollTo({ top: 0 });
    void this._load();
  }

  private _toggle(section: string): void {
    const day = section.slice("day-".length);
    if (section.startsWith("day-") && this._dayLoads.has(day)) this._setDayLoads([day], undefined);
    this._folded = new Map(this._folded).set(section, !this._isCollapsed(section));
  }

  private _isCollapsed(section: string): boolean {
    const open = this._open;
    return this._folded.get(section) ?? (open !== "all" && !(open.startsWith("day-") && section >= open));
  }

  /** Folds anew once filters, view or archive change: the plain timeline opens from its newest day, the rest all open. */
  private _refold(): void {
    const key = JSON.stringify([this._filters, this._view, this._archived]);
    if (key !== this._foldedFor) {
      this._foldedFor = key;
      this._folded = new Map();
      this._open = this._view === "time" && this._unfiltered ? "later" : "all";
    }
    this._settle();
  }

  /** Opens from the newest day listed; the open day only moves back when its notifications are gone. */
  private _settle(): void {
    const open = this._open;
    const days = this._days;
    if (open === "all" || open === "none" || !days?.length) return;
    const newest = this._filters.newestFirst ? days[0]! : days.at(-1)!;
    const day = `day-${newest.day}` as const;
    if (open === "later" || day < open) this._open = day;
  }

  private _foldEvery(collapsed: boolean): void {
    this._open = collapsed ? "none" : "all";
    this._folded = new Map();
  }

  private _sectionKey(record: NotificationRecord): string {
    return this._view === "origin" ? `group-${groupKey(record)}` : `day-${dayKey(this._clock, record.time)}`;
  }

  private _sections(): string[] {
    if (this._days) return this._days.map((day) => `day-${day.day}`);
    return [...new Set(this._records.map((record) => this._sectionKey(record)))];
  }

  private get _byDay(): boolean {
    return this._view === "time" && this._unfiltered;
  }

  private _list(extra: Record<string, unknown>): Promise<Page> {
    return this._hass!.connection.sendMessagePromise<Page>({
      type: "notification_journal/list",
      ...this._query(),
      ...extra,
    });
  }

  /** Adds the records not loaded yet, sorted in; returns how many were new. */
  private _append(records: NotificationRecord[]): number {
    const known = new Set(this._records.map((record) => record.id));
    const fresh = records.filter((record) => !known.has(record.id) && known.add(record.id));
    if (fresh.length) {
      this._records = [...this._records, ...fresh];
      this._arrange();
    }
    return fresh.length;
  }

  /** The loaded records of each day, built once per list of records. */
  private _recordsByDay(): Map<string, NotificationRecord[]> {
    if (this._grouped?.records !== this._records) {
      const days = new Map<string, NotificationRecord[]>();
      for (const record of this._records) {
        const day = dayKey(this._clock, record.time);
        const list = days.get(day);
        if (list) list.push(record);
        else days.set(day, [record]);
      }
      this._grouped = { records: this._records, days };
    }
    return this._grouped.days;
  }

  private _loaded(day: Day): boolean {
    return this._recordsByDay().get(day.day)?.length === day.count;
  }

  /** Loads the days and their counts anew, keeping the notifications loaded; for a day new or gone unseen. */
  private _refreshDays(): void {
    window.clearTimeout(this._daysTimer);
    this._daysTimer = window.setTimeout(() => void this._reloadDays(), 300);
  }

  private async _reloadDays(): Promise<void> {
    if (!this._days || !this._hass) return;
    const request = this._request;
    try {
      const page = await this._list({ ...this._dayQuery, limit: 1 });
      if (request !== this._request || !this._days) return;
      this._days = page.days ?? [];
      if (page.total !== undefined) this._total = page.total;
      this._settle();
    } catch {
      // The next load reports it.
    }
  }

  private get _dayQuery(): Record<string, unknown> {
    return { days: true, time_zone: zoneName(this._clock) };
  }

  /** Counts notifications that arrived or went into their days; a day not listed yet loads the days anew. */
  private _count(records: NotificationRecord[], change: 1 | -1): void {
    const tally = new Map<string, number>();
    for (const record of records) {
      const day = dayKey(this._clock, record.time);
      tally.set(day, (tally.get(day) ?? 0) + change);
    }
    const days = this._days ?? [];
    if ([...tally.keys()].some((day) => !days.some((known) => known.day === day))) this._refreshDays();
    this._days = days
      .map((day) => (tally.has(day.day) ? { ...day, count: day.count + tally.get(day.day)! } : day))
      .filter((day) => day.count > 0);
    this._total = Math.max(0, this._total + change * records.length);
  }

  /** Loads the notifications of the open days not loaded yet, in one span from the oldest to the newest of them. */
  private async _loadOpenDays(): Promise<void> {
    const days = this._days ?? [];
    const wanted = days.filter(
      (day) => !this._dayLoads.has(day.day) && !this._isCollapsed(`day-${day.day}`) && !this._loaded(day),
    );
    if (!wanted.length || !this._hass) return;
    const ends = [wanted[0]!, wanted.at(-1)!].sort((left, right) => compare(left.day, right.day));
    const [first, last] = [ends[0]!, ends[1]!];
    const span = days.filter((day) => day.day >= first.day && day.day <= last.day).map((day) => day.day);
    this._setDayLoads(span, this._localize("loading"));
    const request = this._request;
    const fresh: NotificationRecord[] = [];
    try {
      for (let offset = 0; ; offset += DAY_PAGE_SIZE) {
        const page = await this._list({ since: first.since, until: last.until, limit: DAY_PAGE_SIZE, offset });
        if (request !== this._request) return;
        fresh.push(...page.records);
        if (page.records.length < DAY_PAGE_SIZE) break;
      }
      this._append(fresh);
      this._setDayLoads(span, undefined);
    } catch (error) {
      if (request !== this._request) return;
      this._setDayLoads(span, this._localize("load_failed", { message: errorMessage(error) }));
    }
  }

  /** Marks days as loading, failed with a message, or neither. */
  private _setDayLoads(days: string[], state: string | undefined): void {
    const loads = new Map(this._dayLoads);
    for (const day of days) {
      if (state === undefined) loads.delete(day);
      else loads.set(day, state);
    }
    this._dayLoads = loads;
  }

  private get _unfiltered(): boolean {
    const { newestFirst: _order, text, ...rest } = this._filters;
    return (
      !text.trim() && Object.entries(rest).every(([key, value]) => value === DEFAULT_FILTERS[key as keyof Filters])
    );
  }

  private _set(changes: Partial<Filters>): void {
    this._filters = { ...this._filters, ...changes };
    if ("newestFirst" in changes) store(ORDER_KEY, String(this._filters.newestFirst));
    this.renderRoot.querySelector(".content")?.scrollTo({ top: 0 });
    this._rearrange(Object.keys(changes).every((key) => key === "newestFirst"));
  }

  private _rearrange(local: boolean): void {
    const whole = this._byDay ? !!this._days : !this._days && this._complete;
    if (local && whole && !this._loading) {
      this._arrange();
      const days = this._days;
      if (days && days[0]!.day < days.at(-1)!.day === this._filters.newestFirst) this._days = [...days].reverse();
      this._refold();
    } else {
      if (!this._byDay) this._days = undefined;
      void this._load();
    }
  }

  private _searchInput(event: InputEvent): void {
    this._search = (event.target as HTMLInputElement).value;
    window.clearTimeout(this._searchTimer);
    this._searchTimer = window.setTimeout(() => this._set({ text: this._search }), SEARCH_DELAY);
  }

  private _clearSearch(): void {
    this._search = "";
    window.clearTimeout(this._searchTimer);
    this._set({ text: "" });
  }

  private _reset(): void {
    this._search = "";
    window.clearTimeout(this._searchTimer);
    this._set({ ...DEFAULT_FILTERS, newestFirst: this._filters.newestFirst });
  }

  private _setView(view: View): void {
    if (view === this._view) return;
    this._view = view;
    store(VIEW_KEY, view);
    this._selecting = false;
    this._selected = new Set();
    this.renderRoot.querySelector(".content")?.scrollTo({ top: 0 });
    this._rearrange(true);
  }

  private _lookups(): { userNames: Map<string, string>; originIcons: Map<string, string> } {
    const states = this._hass?.states;
    if (states && states !== this._lookupStates) {
      this._lookupStates = states;
      const names = new Map<string, string>();
      const icons = new Map<string, string>();
      for (const state of Object.values(states)) {
        const domain = state.entity_id.slice(0, state.entity_id.indexOf("."));
        if (domain === "person" && typeof state.attributes.user_id === "string") {
          names.set(state.attributes.user_id, String(state.attributes.friendly_name ?? state.entity_id));
        } else if ((domain === "automation" || domain === "script") && typeof state.attributes.icon === "string") {
          icons.set(state.entity_id, state.attributes.icon);
        }
      }
      if (this._hass?.user) names.set(this._hass.user.id, this._hass.user.name);
      if (!sameMap(names, this._names)) this._names = names;
      if (!sameMap(icons, this._icons)) this._icons = icons;
    }
    return { userNames: this._names, originIcons: this._icons };
  }

  private get _complete(): boolean {
    return this._records.length >= this._total;
  }

  private _arrange(): void {
    const sign = this._filters.newestFirst ? -1 : 1;
    const times = new Map(this._records.map((record) => [record.id, Date.parse(record.time)]));
    const byTime = (left: NotificationRecord, right: NotificationRecord) =>
      sign * (times.get(left.id)! - times.get(right.id)! || compare(left.id, right.id));
    const records = [...this._records];
    if (this._view === "origin") {
      records.sort((left, right) => compare(originRank(left), originRank(right)) || byTime(left, right));
      const groups: Record<string, number> = {};
      for (const record of records) groups[groupKey(record)] = (groups[groupKey(record)] ?? 0) + 1;
      this._groups = groups;
    } else {
      records.sort(byTime);
    }
    this._records = records;
  }

  protected override updated(changed: PropertyValues): void {
    super.updated(changed);
    if (this._days && !this._loading) void this._loadOpenDays();
    const sentinel = this.renderRoot.querySelector(".sentinel.auto");
    if (!sentinel) {
      this._observer?.disconnect();
      this._observer = undefined;
      return;
    }
    if (!this._observer) {
      this._observer = new IntersectionObserver(
        (entries) => {
          if (entries.some((entry) => entry.isIntersecting) && !this._loading && this._records.length < this._total) {
            void this._load(true);
          }
        },
        { root: this.renderRoot.querySelector(".content"), rootMargin: "400px" },
      );
    }
    this._observer.disconnect();
    this._observer.observe(sentinel);
  }

  override render(): TemplateResult {
    const localize = this._localize;
    const showMenu = this.narrow || this._hass?.dockedSidebar === "always_hidden";
    if (this._selecting) {
      const shown = this._shown().length;
      const all = shown > 0 && this._selected.size === shown;
      return html`
        <div class="toolbar selecting">
          <button class="icon-button" title=${localize("done")} @click=${this._endSelection}>
            ${icon(mdiClose, localize("done"))}
          </button>
          <h1>${localize("selected", { count: this._selected.size })}</h1>
          <button
            class="toolbar-button"
            title=${localize(all ? "select_none" : "select_all")}
            aria-label=${localize(all ? "select_none" : "select_all")}
            @click=${this._selectAll}
          >
            ${icon(all ? mdiSelectRemove : mdiSelectAll)}<span>${localize(all ? "select_none" : "select_all")}</span>
          </button>
          <button
            class="toolbar-button strong"
            title=${localize(this._archived ? "restore" : "archive")}
            aria-label=${localize(this._archived ? "restore" : "archive")}
            ?disabled=${!this._selected.size}
            @click=${this._archive}
          >
            ${icon(this._archived ? mdiArchiveArrowUpOutline : mdiArchiveArrowDownOutline)}<span
              >${localize(this._archived ? "restore" : "archive")}</span
            >
          </button>
        </div>
        <div class="content">
          <div class="wrapper">${this._filterBar(localize)} ${this._body(localize)}</div>
        </div>
      `;
    }
    if (this._screen === "statistics") {
      return html`
        <div class="toolbar">
          <button class="icon-button" title=${localize("back")} @click=${() => this._showStatistics(false)}>
            ${icon(mdiArrowLeft, localize("back"))}
          </button>
          <h1>${localize("statistics")}</h1>
          <button class="icon-button" title=${localize("refresh")} @click=${() => void this._statistics?.refresh()}>
            ${icon(mdiRefresh, localize("refresh"))}
          </button>
        </div>
        <div class="content">
          <div class="wrapper">
            <notification-journal-statistics
              .hass=${this._hass}
              .localize=${localize}
              .clock=${this._clock}
              .originIcons=${this._lookups().originIcons}
              @statistics-select=${(event: CustomEvent<StatisticsSelection>) => this._openSelection(event.detail)}
            ></notification-journal-statistics>
          </div>
        </div>
      `;
    }
    return html`
      <div class="toolbar">
        ${
          showMenu
            ? html`<button
                class="icon-button"
                title=${localize("menu")}
                @click=${() => this.dispatchEvent(new CustomEvent("hass-toggle-menu", { bubbles: true, composed: true }))}
              >
                ${icon(mdiMenu, localize("menu"))}
              </button>`
            : nothing
        }
        <h1>${this.panel?.title || localize("title")}</h1>
        <button class="icon-button" title=${localize("statistics")} @click=${() => this._showStatistics(true)}>
          ${icon(mdiChartBar, localize("statistics"))}
        </button>
        <button class="icon-button" title=${localize("refresh")} @click=${() => this._refresh()}>
          ${icon(mdiRefresh, localize("refresh"))}
        </button>
      </div>
      <div class="content">
        <div class="wrapper">${this._filterBar(localize)} ${this._body(localize)}</div>
      </div>
    `;
  }

  private _refresh(): void {
    void this._load();
    void this._loadFacets();
  }

  private _filterBar(localize: Localize): TemplateResult {
    const filters = this._filters;
    const facets = this._facets;
    const select = (value: string, key: keyof Filters, label: string, options: TemplateResult) =>
      html`<label class="select ${value ? "active" : ""}">
        <span class="visually-hidden">${label}</span>
        <select @change=${(event: Event) => this._set({ [key]: (event.target as HTMLSelectElement).value })}>
          ${options}
        </select>
      </label>`;
    return html`
      <div class="filters">
        <div class="search">
          ${icon(mdiMagnify)}
          <input
            type="search"
            .value=${this._search}
            placeholder=${localize("search")}
            aria-label=${localize("search")}
            @input=${this._searchInput}
          />
          ${
            this._search
              ? html`<button class="icon-button small" title=${localize("clear_search")} @click=${this._clearSearch}>
                  ${icon(mdiClose, localize("clear_search"))}
                </button>`
              : nothing
          }
        </div>
        <div class="selects">
          <div class="view" role="group" aria-label=${localize("view")}>
            ${(["time", "origin"] as View[]).map(
              (view) =>
                html`<button
                  class=${this._view === view ? "selected" : ""}
                  aria-pressed=${this._view === view ? "true" : "false"}
                  @click=${() => this._setView(view)}
                >
                  ${icon(view === "time" ? mdiCalendarClockOutline : mdiRobotOutline)}
                  <span>${localize(view === "time" ? "view_time" : "view_origin")}</span>
                </button>`,
            )}
          </div>
          ${select(
            filters.status,
            "status",
            localize("status_all"),
            html`<option value="" ?selected=${!filters.status}>${localize("status_all")}</option>
              ${STATUSES.map(
                (status) =>
                  html`<option value=${status} ?selected=${filters.status === status}>
                    ${localize(`status_${status}`)}
                  </option>`,
              )}`,
          )}
          ${select(
            filters.origin,
            "origin",
            localize("origin_all"),
            html`<option value="" ?selected=${!filters.origin}>${localize("origin_all")}</option>
              ${
                filters.origin && !facets.origins.some((option) => option.id === filters.origin)
                  ? html`<option value=${filters.origin} selected>
                      ${this._originNames.get(filters.origin) ?? filters.origin}
                    </option>`
                  : nothing
              }
              ${facets.origins.map(
                (option) =>
                  html`<option value=${option.id} ?selected=${filters.origin === option.id}>
                    ${originName(localize, option.id, option.name)}
                  </option>`,
              )}`,
          )}
          ${select(
            typeof filters.period === "object" ? "range" : filters.period,
            "period",
            localize("period_all"),
            html`<option value="" ?selected=${!filters.period}>${localize("period_all")}</option>
              ${
                typeof filters.period === "object"
                  ? html`<option value="range" selected>${filters.period.label}</option>`
                  : nothing
              }
              ${(Object.keys(PERIODS) as Exclude<Period, "">[]).map(
                (period) =>
                  html`<option value=${period} ?selected=${filters.period === period}>
                    ${localize(`period_${period}`)}
                  </option>`,
              )}`,
          )}
          ${
            filters.tag
              ? html`<button
                  class="sort active tag-filter"
                  title=${localize("remove_tag_filter")}
                  @click=${() => this._set({ tag: "" })}
                >
                  ${icon(mdiTagOutline)}<span>${filters.tag}</span>${icon(mdiClose)}
                </button>`
              : nothing
          }
        </div>
        <div class="options">
          <div class="view" role="group" aria-label=${localize("archive_view")}>
            ${[false, true].map(
              (archived) =>
                html`<button
                  class=${this._archived === archived ? "selected" : ""}
                  aria-pressed=${this._archived === archived ? "true" : "false"}
                  @click=${() => this._setArchived(archived)}
                >
                  ${icon(archived ? mdiArchiveOutline : mdiInboxOutline)}
                  <span>${localize(archived ? "tab_archived" : "tab_active")}</span>
                </button>`,
            )}
          </div>
          <button
            class="sort"
            title=${localize(filters.newestFirst ? "newest_first" : "oldest_first")}
            @click=${() => this._set({ newestFirst: !filters.newestFirst })}
          >
            ${icon(filters.newestFirst ? mdiSortClockDescendingOutline : mdiSortClockAscendingOutline)}
            <span>${localize(filters.newestFirst ? "newest_first" : "oldest_first")}</span>
          </button>
          <span class="spacer"></span>
          ${
            this._selecting || !this._records.length
              ? nothing
              : html`<button class="text-button" @click=${() => (this._selecting = true)}>
                  ${icon(mdiCheckboxMultipleMarkedOutline)}${localize("select")}
                </button>`
          }
        </div>
        <div class="summary">
          <span>${this._error ? nothing : countText(localize, this._total, "count_one", "count")}</span>
          ${this._notice ? html`<span class="notice">${this._notice}</span>` : nothing}
          <span class="spacer"></span>
          ${this._foldAll(localize)}
          ${
            this._unfiltered
              ? nothing
              : html`<button class="text-button" @click=${this._reset}>
                  ${icon(mdiFilterRemoveOutline)}${localize("reset_filters")}
                </button>`
          }
        </div>
        ${this._keptNotice(localize)}
      </div>
    `;
  }

  /** Say so when the list opened from the statistics reaches back further than single notifications are kept. */
  private _keptNotice(localize: Localize): TemplateResult | typeof nothing {
    const period = this._filters.period;
    const kept = this._keptSince;
    if (typeof period !== "object" || !kept || Date.parse(kept) <= Date.parse(period.since)) return nothing;
    const clock = this._clock;
    const date = formatter(clock.language, { dateStyle: "medium", timeZone: clock.timeZone }).format(new Date(kept));
    return html`<p class="kept">${localize("kept_since", { date })}</p>`;
  }

  private _foldAll(localize: Localize): TemplateResult | typeof nothing {
    const sections = this._sections();
    if (sections.length < 2) return nothing;
    const expand = sections.every((section) => this._isCollapsed(section));
    return html`<button class="text-button" @click=${() => this._foldEvery(!expand)}>
      ${icon(expand ? mdiUnfoldMoreHorizontal : mdiUnfoldLessHorizontal)}${localize(expand ? "expand_all" : "collapse_all")}
    </button>`;
  }

  private _body(localize: Localize): TemplateResult {
    if (this._error) {
      return html`<div class="empty">
        ${icon(mdiMessageBadgeOutline)}
        <p>${this._error}</p>
      </div>`;
    }
    const days = this._days;
    if (days ? !days.length : !this._records.length) {
      if (this._loading) return html`<div class="empty"><p>${localize("loading")}</p></div>`;
      return this._unfiltered
        ? html`<div class="empty">
            ${icon(this._archived ? mdiArchiveOutline : mdiMessageBadgeOutline)}
            <h2>${localize(this._archived ? "empty_archive" : "empty")}</h2>
            <p>${localize(this._archived ? "empty_archive_hint" : "empty_hint")}</p>
          </div>`
        : html`<div class="empty">
            ${icon(mdiFilterRemoveOutline)}
            <h2>${localize("no_match")}</h2>
            <button class="text-button" @click=${this._reset}>${localize("reset_filters")}</button>
          </div>`;
    }
    const clock = this._clock;
    const admin = this._admin;
    const { userNames, originIcons } = this._lookups();
    const byOrigin = this._view === "origin";
    const items: Item[] = [];
    let collapsed = false;
    if (days) {
      const recordsByDay = this._recordsByDay();
      for (const day of days) {
        collapsed = this._isCollapsed(`day-${day.day}`);
        items.push({ day: day.day, collapsed, count: day.count });
        if (collapsed) continue;
        if (this._loaded(day)) for (const record of recordsByDay.get(day.day) ?? []) items.push({ record });
        else items.push({ waiting: day.day });
      }
    } else {
      let section = "";
      for (const record of this._records) {
        const key = byOrigin ? groupKey(record) : dayKey(clock, record.time);
        if (key !== section) {
          section = key;
          collapsed = this._isCollapsed(byOrigin ? `group-${key}` : `day-${key}`);
          items.push(byOrigin ? { group: key, record } : { day: key, collapsed });
        }
        if (!collapsed) items.push({ record });
      }
    }
    return html`
      ${
        this._pending
          ? html`<button class="pending" @click=${() => this._load()}>
              ${countText(localize, this._pending, "new_records_one", "new_records")}
            </button>`
          : nothing
      }
      <div
        class="list ${this._loading ? "busy" : ""}"
        @notification-select=${(event: CustomEvent<{ id: string }>) => this._select(event.detail.id)}
        @notification-tag=${(event: CustomEvent<{ tag: string }>) => this._set({ tag: event.detail.tag })}
      >
        ${repeat(
          items,
          (item) =>
            "day" in item
              ? `day-${item.day}`
              : "group" in item
                ? `group-${item.group}`
                : "waiting" in item
                  ? `waiting-${item.waiting}`
                  : item.record.id,
          (item) =>
            "day" in item
              ? html`<button
                  class="section day ${item.collapsed ? "collapsed" : ""}"
                  aria-expanded=${item.collapsed ? "false" : "true"}
                  @click=${() => this._toggle(`day-${item.day}`)}
                >
                  ${icon(mdiChevronDown)}<span>${dayLabel(clock, localize, item.day)}</span>
                  ${item.count === undefined ? nothing : html`<span class="group-count">${item.count}</span>`}
                </button>`
              : "waiting" in item
                ? html`<p class="waiting">${this._dayLoads.get(item.waiting) ?? localize("loading")}</p>`
                : "group" in item
                  ? this._groupHeader(localize, item.group, item.record, originIcons)
                  : html`<notification-journal-record
                      .record=${item.record}
                      .localize=${localize}
                      .clock=${clock}
                      .userNames=${userNames}
                      .originIcons=${originIcons}
                      .sign=${this._sign}
                      .resend=${admin ? this._resend : undefined}
                      ?admin=${admin}
                      ?showDate=${byOrigin}
                      ?selectable=${this._selecting}
                      ?selected=${this._selected.has(item.record.id)}
                    ></notification-journal-record>`,
        )}
      </div>
      ${
        !days && this._records.length < this._total
          ? html`<div class="sentinel ${collapsed ? "" : "auto"}">
              <button class="text-button" ?disabled=${this._loading} @click=${() => this._load(true)}>
                ${localize(this._loading ? "loading" : "load_more")}
              </button>
            </div>`
          : nothing
      }
    `;
  }

  private _groupHeader(
    localize: Localize,
    key: string,
    record: NotificationRecord,
    originIcons: Map<string, string>,
  ): TemplateResult {
    const origin = record.origin;
    const name = originName(localize, key, origin.name);
    const glyph = originGlyph(origin, originIcons);
    const section = `group-${key}`;
    const collapsed = this._isCollapsed(section);
    return html`<button
      class="section group ${collapsed ? "collapsed" : ""}"
      aria-expanded=${collapsed ? "false" : "true"}
      @click=${() => this._toggle(section)}
    >
      <span class="group-icon">${glyph}</span>
      <span class="group-name">${name}</span>
      <span class="group-count">${this._groups[key] ?? ""}</span>
      ${icon(mdiChevronDown)}
    </button>`;
  }

  static override styles = css`
    ${controlStyles}
    :host {
      display: flex;
      flex-direction: column;
      height: 100%;
      background: var(--primary-background-color);
      color: var(--primary-text-color);
      font-family: var(--ha-font-family-body);
      -webkit-font-smoothing: antialiased;
    }
    .toolbar {
      flex: none;
      display: flex;
      align-items: center;
      gap: 4px;
      box-sizing: border-box;
      height: calc(var(--header-height, 56px) + var(--safe-area-inset-top, 0px));
      padding: var(--safe-area-inset-top, 0px) 8px 0 12px;
      background: var(--app-header-background-color);
      color: var(--app-header-text-color);
      border-bottom: var(--app-header-border-bottom);
    }
    h1 {
      flex: 1;
      margin: 0 0 0 12px;
      font-size: 1.25rem;
      font-weight: 400;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .content {
      flex: 1;
      overflow-y: auto;
      padding-bottom: var(--safe-area-inset-bottom, 0px);
    }
    .wrapper {
      max-width: 1040px;
      margin: 0 auto;
      padding: 16px 16px 32px;
      box-sizing: border-box;
    }
    .filters {
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .search {
      display: flex;
      align-items: center;
      gap: 8px;
      height: 48px;
      padding: 0 8px 0 14px;
      border-radius: 24px;
      background: var(--card-background-color);
      border: 1px solid var(--divider-color);
      color: var(--secondary-text-color);
    }
    .search:focus-within {
      border-color: var(--primary-color);
    }
    .search input {
      flex: 1;
      min-width: 0;
      height: 100%;
      border: none;
      outline: none;
      background: none;
      color: var(--primary-text-color);
      font: inherit;
      font-size: 1rem;
    }
    .search input::-webkit-search-cancel-button {
      display: none;
    }
    .selects {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .select {
      position: relative;
      display: inline-flex;
      max-width: 200px;
    }
    .select select {
      width: 100%;
    }
    .select::after {
      content: "";
      position: absolute;
      right: 12px;
      top: 50%;
      width: 6px;
      height: 6px;
      margin-top: -5px;
      border-right: 2px solid currentColor;
      border-bottom: 2px solid currentColor;
      transform: rotate(45deg);
      pointer-events: none;
      color: var(--secondary-text-color);
    }
    select,
    .sort {
      appearance: none;
      max-width: 100%;
      height: 34px;
      padding: 0 32px 0 14px;
      border-radius: 17px;
      border: 1px solid var(--divider-color);
      background: var(--card-background-color);
      color: var(--primary-text-color);
      font: inherit;
      font-size: 0.875rem;
      text-overflow: ellipsis;
      cursor: pointer;
    }
    .select.active select,
    .sort.active {
      border-color: var(--primary-color);
      background: color-mix(in srgb, var(--primary-color) 12%, var(--card-background-color));
    }
    .tag-filter {
      max-width: 220px;
    }
    .tag-filter span {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    option,
    optgroup {
      color: var(--primary-text-color);
      background: var(--card-background-color);
    }
    .sort {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 0 14px 0 10px;
    }
    .sort .icon {
      width: 18px;
      height: 18px;
      color: var(--secondary-text-color);
    }
    .summary {
      display: flex;
      align-items: center;
      justify-content: space-between;
      min-height: 32px;
      color: var(--secondary-text-color);
      font-size: 0.875rem;
    }
    .text-button {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 10px;
      border: none;
      border-radius: 6px;
      background: none;
      color: var(--primary-color);
      font: inherit;
      font-size: 0.875rem;
      font-weight: 500;
      cursor: pointer;
    }
    .text-button .icon {
      width: 18px;
      height: 18px;
    }
    .text-button:hover {
      background: color-mix(in srgb, var(--primary-color) 10%, transparent);
    }
    .text-button[disabled] {
      color: var(--disabled-text-color);
      cursor: default;
    }
    .list {
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .section {
      display: flex;
      align-items: center;
      width: 100%;
      border: none;
      text-align: left;
      font-family: inherit;
      cursor: pointer;
    }
    .section > .icon {
      width: 20px;
      height: 20px;
      color: var(--secondary-text-color);
      transition: transform 0.15s;
    }
    .section.collapsed > .icon {
      transform: rotate(-90deg);
    }
    .day {
      gap: 6px;
      margin: 14px 0 0;
      padding: 4px 0;
      background: none;
      font-size: 0.8rem;
      font-weight: 500;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--secondary-text-color);
    }
    .day:first-child {
      margin-top: 4px;
    }
    .group {
      position: sticky;
      top: 0;
      z-index: 1;
      display: flex;
      align-items: center;
      gap: 10px;
      margin: 14px 0 0;
      padding: 8px 4px;
      font-size: 1rem;
      font-weight: 500;
      color: var(--primary-text-color);
      background: var(--primary-background-color);
    }
    .group:first-child {
      margin-top: 0;
    }
    .section.collapsed + .section {
      margin-top: 4px;
    }
    .spacer {
      flex: 1;
    }
    .notice {
      margin-left: 12px;
      color: var(--error-color);
    }
    .kept {
      margin: 0;
      color: var(--secondary-text-color);
      font-size: 0.875rem;
    }
    .group-icon {
      display: grid;
      place-items: center;
      width: 32px;
      height: 32px;
      border-radius: 50%;
      color: var(--primary-color);
      background: color-mix(in srgb, var(--primary-color) 14%, transparent);
    }
    .group-icon .icon {
      width: 18px;
      height: 18px;
    }
    .group-icon ha-icon {
      --mdc-icon-size: 18px;
      display: inline-flex;
    }
    .group-name {
      flex: 1;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .day .group-count {
      letter-spacing: normal;
      font-weight: 400;
    }
    .waiting {
      margin: 8px 0;
      color: var(--secondary-text-color);
      font-size: 0.875rem;
    }
    .group-count {
      min-width: 22px;
      padding: 1px 8px;
      box-sizing: border-box;
      border-radius: 11px;
      font-size: 0.8rem;
      text-align: center;
      color: var(--secondary-text-color);
      background: var(--secondary-background-color);
    }
    .options {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
    }
    .toolbar.selecting {
      background: var(--primary-color);
      color: var(--text-primary-color);
    }
    .toolbar-button {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      height: 36px;
      padding: 0 12px;
      border: none;
      border-radius: 18px;
      background: none;
      color: inherit;
      font: inherit;
      font-size: 0.875rem;
      font-weight: 500;
      cursor: pointer;
    }
    .toolbar-button .icon {
      width: 20px;
      height: 20px;
    }
    .toolbar-button:hover {
      background: color-mix(in srgb, currentColor 12%, transparent);
    }
    .toolbar-button.strong {
      background: color-mix(in srgb, currentColor 18%, transparent);
    }
    .toolbar-button[disabled] {
      opacity: 0.5;
      cursor: default;
    }
    .pending {
      position: sticky;
      top: 8px;
      z-index: 1;
      display: block;
      margin: 0 auto 10px;
      padding: 8px 18px;
      border: none;
      border-radius: 18px;
      background: var(--primary-color);
      color: var(--text-primary-color);
      font: inherit;
      font-size: 0.875rem;
      font-weight: 500;
      box-shadow: var(--ha-card-box-shadow, none);
      cursor: pointer;
    }
    .sentinel {
      display: flex;
      justify-content: center;
      padding: 16px 0;
    }
    .visually-hidden {
      position: absolute;
      width: 1px;
      height: 1px;
      overflow: hidden;
      clip-path: inset(50%);
      white-space: nowrap;
    }
    @media (max-width: 600px) {
      .wrapper {
        padding: 12px 8px 24px;
      }
      .selects {
        display: grid;
        grid-template-columns: 1fr 1fr;
      }
      .view {
        grid-column: 1 / -1;
      }
      .toolbar-button span {
        display: none;
      }
      .toolbar-button {
        padding: 0 10px;
      }
      .view button {
        flex: 1;
        justify-content: center;
      }
      .select {
        max-width: none;
      }
      .sort {
        justify-content: center;
      }
    }
  `;
}

if (!customElements.get("notification-journal-panel")) {
  customElements.define("notification-journal-panel", NotificationJournalPanel);
}
