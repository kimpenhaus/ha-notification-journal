import { css, html, LitElement, nothing, svg, type PropertyValues, type TemplateResult } from "lit";

import { type Clock, formatter } from "./format";
import { icon, mdiChevronLeft, mdiChevronRight, mdiFlashOutline } from "./icons";
import type { Localize } from "./localize";
import { originGlyph } from "./record";
import type {
  HomeAssistant,
  Origin,
  OriginKind,
  OriginStatistics,
  Statistics,
  StatisticsPeriod,
  StatisticsSelection,
} from "./types";

const PERIODS: StatisticsPeriod[] = ["day", "week", "month", "year"];
const PERIOD_KEY = "notification_journal.statistics_period";
const WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];
/** Origins beyond this many share the colour of "other". */
const COLOURED = 6;
const OTHER = "";
const CHART_HEIGHT = 220;
const AXIS_WIDTH = 32;
const LABEL_HEIGHT = 22;
const HEAT_LEVELS = 5;

type WeekInfoLocale = Intl.Locale & { getWeekInfo?: () => { firstDay: number }; weekInfo?: { firstDay: number } };

const languageWeekdays = new Map<string, number>();

/** The first day of the week the user chose in their profile, else the one of their language; Monday is 0. */
function firstWeekday(hass: HomeAssistant): number {
  const chosen = WEEKDAYS.indexOf(hass.locale?.first_weekday ?? "");
  if (chosen >= 0) return chosen;
  const language = hass.locale?.language ?? hass.language;
  let first = languageWeekdays.get(language);
  if (first === undefined) {
    first = 0;
    try {
      const locale = new Intl.Locale(language) as WeekInfoLocale;
      const info = locale.getWeekInfo?.() ?? locale.weekInfo;
      if (info) first = (info.firstDay + 6) % 7;
    } catch {
      // Without week information the week starts on Monday.
    }
    languageWeekdays.set(language, first);
  }
  return first;
}

function originOf(key: string): Origin {
  const domain = key.slice(0, key.indexOf("."));
  const kind: OriginKind =
    domain === "automation" || domain === "script" || domain === "integration" ? domain : (key as OriginKind);
  return {
    kind,
    entity_id: kind === "automation" || kind === "script" ? key : null,
    name: null,
    trace_key: null,
    run_id: null,
    user_id: null,
    integration: kind === "integration" ? key.slice(domain.length + 1) : null,
  };
}

function colour(slot: number): string {
  return slot ? `var(--graph-color-${slot}, var(--color-${slot}))` : "var(--disabled-text-color)";
}

function niceStep(max: number): number {
  const raw = Math.max(1, max) / 4;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  for (const factor of [1, 2, 2.5, 5, 10]) if (factor * magnitude >= raw) return Math.max(1, factor * magnitude);
  return 10 * magnitude;
}

/** The ISO week of a local date; it is counted from Monday, so it is shown only for weeks starting on Monday. */
function isoWeek(year: number, month: number, day: number): number {
  const date = new Date(Date.UTC(year, month - 1, day));
  date.setUTCDate(date.getUTCDate() - ((date.getUTCDay() + 6) % 7) + 3);
  const first = new Date(Date.UTC(date.getUTCFullYear(), 0, 4));
  return 1 + Math.round(((date.getTime() - first.getTime()) / 86_400_000 - 3 + ((first.getUTCDay() + 6) % 7)) / 7);
}

export class NotificationJournalStatistics extends LitElement {
  static override properties = {
    hass: { attribute: false },
    localize: { attribute: false },
    clock: { attribute: false },
    originIcons: { attribute: false },
    _period: { state: true },
    _offset: { state: true },
    _data: { state: true },
    _error: { state: true },
    _loading: { state: true },
    _width: { state: true },
    _hover: { state: true },
  };

  declare hass: HomeAssistant;
  declare localize: Localize;
  declare clock: Clock;
  declare originIcons: Map<string, string>;
  declare _period: StatisticsPeriod;
  declare _offset: number;
  declare _data: Statistics | undefined;
  declare _error: string | undefined;
  declare _loading: boolean;
  declare _width: number;
  declare _hover: number | undefined;

  private _request = 0;
  private _resize?: ResizeObserver;

  constructor() {
    super();
    let period: string | null = null;
    try {
      period = window.localStorage.getItem(PERIOD_KEY);
    } catch {
      // Without storage the statistics open on a week.
    }
    this._period = PERIODS.includes(period as StatisticsPeriod) ? (period as StatisticsPeriod) : "week";
    this._offset = 0;
    this._loading = false;
    this._width = 0;
  }

  /** The panel's styles apply: the view lives in its shadow root. */
  protected override createRenderRoot(): HTMLElement {
    return this;
  }

  override connectedCallback(): void {
    super.connectedCallback();
    void this.refresh();
  }

  override disconnectedCallback(): void {
    super.disconnectedCallback();
    this._resize?.disconnect();
    this._resize = undefined;
  }

  protected override updated(changed: PropertyValues): void {
    super.updated(changed);
    const chart = this.querySelector<HTMLElement>(".chart");
    if (chart && !this._resize) {
      this._resize = new ResizeObserver(([entry]) => {
        const width = Math.round(entry.contentRect.width);
        if (width !== this._width) this._width = width;
      });
      this._resize.observe(chart);
    }
  }

  /** Load the statistics of the shown period again. */
  async refresh(): Promise<void> {
    if (!this.hass) return;
    const request = ++this._request;
    this._loading = true;
    try {
      const data = await this.hass.connection.sendMessagePromise<Statistics>({
        type: "notification_journal/statistics",
        period: this._period,
        offset: this._offset,
        first_weekday: firstWeekday(this.hass),
        time_zone: this.clock.timeZone ?? Intl.DateTimeFormat().resolvedOptions().timeZone,
      });
      if (request !== this._request) return;
      this._data = data;
      this._error = undefined;
    } catch (error) {
      if (request !== this._request) return;
      const message = typeof error === "object" && error && "message" in error ? String(error.message) : String(error);
      this._error = this.localize("stats_failed", { message });
    } finally {
      if (request === this._request) this._loading = false;
    }
  }

  private _show(period: StatisticsPeriod, offset: number): void {
    if (period !== this._period) {
      try {
        window.localStorage.setItem(PERIOD_KEY, period);
      } catch {
        // The choice lasts until the page reloads.
      }
    }
    this._period = period;
    this._offset = offset;
    this._hover = undefined;
    void this.refresh();
  }

  private _select(selection: Omit<StatisticsSelection, "keptSince">): void {
    this.dispatchEvent(
      new CustomEvent<StatisticsSelection>("statistics-select", {
        detail: { ...selection, keptSince: this._data?.kept_since ?? null },
        bubbles: true,
        composed: true,
      }),
    );
  }

  private _format(iso: string, options: Intl.DateTimeFormatOptions): string {
    return formatter(this.clock.language, { ...options, timeZone: this.clock.timeZone }).format(new Date(iso));
  }

  private _rangeLabel(data: Statistics): string {
    const start = new Date(data.start);
    const last = new Date(new Date(data.end).getTime() - 1);
    const zone = this.clock.timeZone;
    const language = this.clock.language;
    switch (data.period) {
      case "day":
        return this._format(data.start, { weekday: "short", day: "numeric", month: "long", year: "numeric" });
      case "week": {
        const range = formatter(language, { day: "numeric", month: "short", timeZone: zone }).formatRange(start, last);
        if (firstWeekday(this.hass) !== 0) return range;
        const [year, month, day] = formatter("en-CA", { timeZone: zone }).format(start).split("-").map(Number);
        return `${this.localize("week_number", { week: isoWeek(year, month, day) })} · ${range}`;
      }
      case "month":
        return this._format(data.start, { month: "long", year: "numeric" });
      default:
        return this._format(data.start, { year: "numeric" });
    }
  }

  private _bucketLabel(period: StatisticsPeriod, iso: string, index: number, count: number): string {
    if (period === "day") return index % 3 === 0 ? this._format(iso, { hour: "numeric" }) : "";
    if (period === "week") return this._format(iso, { weekday: "short", day: "numeric" });
    if (period === "month") return index === 0 || (index + 1) % 5 === 0 || index === count - 1 ? String(index + 1) : "";
    return this._format(iso, { month: "short" });
  }

  private _bucketTitle(period: StatisticsPeriod, iso: string): string {
    if (period === "day")
      return this._format(iso, { weekday: "short", day: "numeric", month: "short", hour: "numeric" });
    if (period === "year") return this._format(iso, { month: "long", year: "numeric" });
    return this._format(iso, { weekday: "long", day: "numeric", month: "long" });
  }

  private _name(origin: OriginStatistics | undefined, key: string): string {
    if (key === OTHER) return this.localize("other_origins");
    if (origin?.name) return origin.name;
    const kind = originOf(key).kind;
    if (kind === "user") return this.localize("origin_by_hand");
    if (kind === "system") return this.localize("origin_system");
    if (kind === "unknown") return this.localize("origin_unknown");
    return key;
  }

  override render(): TemplateResult {
    const localize = this.localize;
    const data = this._data;
    return html`
      <div class="stats-controls">
        <div class="view" role="group" aria-label=${localize("stats_period")}>
          ${PERIODS.map(
            (period) =>
              html`<button
                class=${this._period === period ? "selected" : ""}
                aria-pressed=${this._period === period ? "true" : "false"}
                @click=${() => this._show(period, 0)}
              >
                ${localize(`stats_${period}`)}
              </button>`,
          )}
        </div>
        <div class="stats-nav">
          <button
            class="icon-button small"
            title=${localize("earlier")}
            ?disabled=${!data?.has_older}
            @click=${() => this._show(this._period, this._offset + 1)}
          >
            ${icon(mdiChevronLeft, localize("earlier"))}
          </button>
          <span class="stats-range">${data && data.period === this._period ? this._rangeLabel(data) : ""}</span>
          <button
            class="icon-button small"
            title=${localize("later")}
            ?disabled=${this._offset === 0}
            @click=${() => this._show(this._period, this._offset - 1)}
          >
            ${icon(mdiChevronRight, localize("later"))}
          </button>
        </div>
      </div>
      ${
        this._error
          ? html`<div class="empty"><p>${this._error}</p></div>`
          : data
            ? html`<div class="stats ${this._loading ? "busy" : ""}">${this._content(data)}</div>`
            : html`<div class="empty"><p>${localize("loading")}</p></div>`
      }
    `;
  }

  private _content(data: Statistics): TemplateResult {
    const localize = this.localize;
    const slots = new Map<string, number>();
    data.origins.slice(0, COLOURED).forEach((origin, index) => slots.set(origin.key, index + 1));
    const byKey = new Map(data.origins.map((origin) => [origin.key, origin]));
    return html`
      ${this._tiles(data, byKey)}
      <section class="stats-box">
        <div class="stats-head">
          <h2>${localize("history")}</h2>
          <span>${localize("history_hint")}</span>
        </div>
        ${this._legend(data, slots, byKey)} ${this._chart(data, slots, byKey)}
      </section>
      <div class="stats-columns">
        <section class="stats-box">
          <div class="stats-head">
            <h2>${localize("when")}</h2>
            <span>${localize("when_hint")}</span>
          </div>
          ${this._heatmap(data)}
        </section>
        <section class="stats-box">
          <div class="stats-head">
            <h2>${localize("who")}</h2>
            <span>${localize("who_hint")}</span>
          </div>
          ${this._ranking(data, slots)}
        </section>
      </div>
    `;
  }

  private _change(current: number, previous: number): string {
    if (!previous) return current ? this.localize("trend_new") : "±0";
    const change = Math.round((100 * (current - previous)) / previous);
    if (change === 0) return "±0 %";
    return `${change > 0 ? "↑ +" : "↓ −"}${new Intl.NumberFormat(this.clock.language).format(Math.abs(change))} %`;
  }

  private _top(data: Statistics, field: "night" | "bursts", byKey: Map<string, OriginStatistics>): string | undefined {
    const top = [...data.origins].sort((left, right) => right[field] - left[field])[0];
    return top && top[field] ? this._name(byKey.get(top.key), top.key) : undefined;
  }

  private _tiles(data: Statistics, byKey: Map<string, OriginStatistics>): TemplateResult {
    const localize = this.localize;
    const number = new Intl.NumberFormat(this.clock.language);
    const totals = data.totals;
    const night = this._top(data, "night", byKey);
    const bursts = this._top(data, "bursts", byKey);
    const tile = (label: string, value: string, note: string, title?: string) =>
      html`<div class="stats-tile" title=${title ?? nothing}>
        <span class="tile-label">${label}</span>
        <span class="tile-value">${value}</span>
        <span class="tile-note">${note}</span>
      </div>`;
    return html`<div class="stats-tiles">
      ${tile(
        localize("tile_notifications"),
        number.format(totals.notifications),
        localize(`compare_${data.period}`, { change: this._change(totals.notifications, data.previous.notifications) }),
      )}
      ${tile(
        localize("tile_answered"),
        totals.with_buttons ? `${number.format(Math.round((100 * totals.answered) / totals.with_buttons))} %` : "–",
        totals.with_buttons
          ? localize("answered_of", {
              answered: number.format(totals.answered),
              total: number.format(totals.with_buttons),
            })
          : localize("no_buttons"),
      )}
      ${tile(
        localize("tile_night"),
        number.format(totals.night),
        night ? localize("mostly", { name: night }) : localize("quiet"),
      )}
      ${tile(
        localize("tile_bursts"),
        number.format(totals.bursts),
        bursts ? localize("mostly", { name: bursts }) : localize("bursts_hint"),
        localize("bursts_hint"),
      )}
    </div>`;
  }

  private _legend(data: Statistics, slots: Map<string, number>, byKey: Map<string, OriginStatistics>): TemplateResult {
    if (!data.totals.notifications) return html`<p class="stats-empty">${this.localize("no_statistics")}</p>`;
    const shown = data.origins.filter((origin) => origin.notifications && slots.has(origin.key));
    const other = data.origins.some((origin) => origin.notifications && !slots.has(origin.key));
    return html`<div class="legend">
      ${shown.map(
        (origin) =>
          html`<span
            ><i class="swatch" style="background:${colour(slots.get(origin.key)!)}"></i>${this._name(
              byKey.get(origin.key),
              origin.key,
            )}</span
          >`,
      )}
      ${other ? html`<span><i class="swatch" style="background:${colour(0)}"></i>${this.localize("other_origins")}</span>` : nothing}
    </div>`;
  }

  private _chart(data: Statistics, slots: Map<string, number>, byKey: Map<string, OriginStatistics>): TemplateResult {
    const width = Math.max(this._width, 280);
    const now = Date.now();
    const columns = data.buckets.map((bucket, index) => {
      const stacks = new Map<number, { key: string; count: number }>();
      for (const [key, count] of Object.entries(bucket.counts)) {
        const slot = slots.get(key) ?? 0;
        const stack = stacks.get(slot);
        stacks.set(slot, { key: slot ? key : OTHER, count: (stack?.count ?? 0) + count });
      }
      const segments = [...stacks.entries()]
        .sort(([left], [right]) => (left || COLOURED + 1) - (right || COLOURED + 1))
        .map(([slot, stack]) => ({ slot, ...stack }));
      const until = data.buckets[index + 1]?.start ?? data.end;
      return {
        start: bucket.start,
        until,
        segments,
        total: segments.reduce((sum, segment) => sum + segment.count, 0),
        future: new Date(bucket.start).getTime() > now,
      };
    });
    const max = Math.max(0, ...columns.map((column) => column.total));
    const step = niceStep(max);
    const top = Math.max(step, Math.ceil(max / step) * step);
    const plotWidth = width - AXIS_WIDTH;
    const plotHeight = CHART_HEIGHT - LABEL_HEIGHT - 8;
    const columnWidth = plotWidth / columns.length;
    const barWidth = Math.max(3, Math.min(40, columnWidth * 0.62));
    const y = (value: number) => 8 + plotHeight - (value / top) * plotHeight;
    const ticks: number[] = [];
    for (let value = 0; value <= top; value += step) ticks.push(value);
    const hovered = this._hover !== undefined ? columns[this._hover] : undefined;
    return html`<div class="chart" @pointerleave=${() => (this._hover = undefined)}>
      <svg
        viewBox="0 0 ${width} ${CHART_HEIGHT}"
        width=${width}
        height=${CHART_HEIGHT}
        role="img"
        aria-label=${this.localize("history")}
      >
        ${ticks.map(
          (value) =>
            svg`<line class=${value ? "grid" : "baseline"} x1=${AXIS_WIDTH} x2=${width} y1=${y(value)} y2=${y(value)}></line>
              <text class="axis" x=${AXIS_WIDTH - 6} y=${y(value) + 4} text-anchor="end">${value}</text>`,
        )}
        ${columns.map((column, index) => {
          const center = AXIS_WIDTH + columnWidth * index + columnWidth / 2;
          const x = center - barWidth / 2;
          let base = 0;
          const marks = column.segments.map((segment, position) => {
            const bottom = y(base);
            base += segment.count;
            const gap = position ? 2 : 0;
            const height = Math.max(1, bottom - y(base) - gap);
            const topEdge = bottom - gap - height;
            if (position < column.segments.length - 1) {
              return svg`<rect x=${x} y=${topEdge} width=${barWidth} height=${height} fill=${colour(segment.slot)}></rect>`;
            }
            const radius = Math.min(4, height, barWidth / 2);
            return svg`<path fill=${colour(segment.slot)} d="M${x} ${topEdge + height}V${topEdge + radius}Q${x} ${topEdge} ${x + radius} ${topEdge}H${x + barWidth - radius}Q${x + barWidth} ${topEdge} ${x + barWidth} ${topEdge + radius}V${topEdge + height}Z"></path>`;
          });
          const label = this._bucketLabel(data.period, column.start, index, columns.length);
          return svg`${marks}
            ${label ? svg`<text class=${column.future ? "axis future" : "axis"} x=${center} y=${CHART_HEIGHT - 6} text-anchor="middle">${label}</text>` : nothing}
            ${
              column.future || !column.total
                ? nothing
                : svg`<rect class="hit" x=${AXIS_WIDTH + columnWidth * index} y="8" width=${columnWidth} height=${plotHeight} rx="4"
                    @pointerenter=${() => (this._hover = index)}
                    @click=${() =>
                      this._select({
                        since: column.start,
                        until: column.until,
                        label: this._bucketTitle(data.period, column.start),
                      })}
                  ></rect>`
            }`;
        })}
      </svg>
      ${
        hovered
          ? html`<div
              class="chart-tip ${this._hover! > columns.length / 2 ? "left" : ""}"
              style="--x:${AXIS_WIDTH + columnWidth * (this._hover! + (this._hover! > columns.length / 2 ? 0 : 1))}px"
            >
              <span class="chart-tip-head"
                >${this._bucketTitle(data.period, hovered.start)}<b>${hovered.total}</b></span
              >
              ${[...hovered.segments]
                .reverse()
                .map(
                  (segment) =>
                    html`<span
                      ><i class="swatch" style="background:${colour(segment.slot)}"></i>${this._name(
                        byKey.get(segment.key),
                        segment.key,
                      )}<b>${segment.count}</b></span
                    >`,
                )}
            </div>`
          : nothing
      }
    </div>`;
  }

  private _heatmap(data: Statistics): TemplateResult {
    const first = firstWeekday(this.hass);
    const rows = Array.from({ length: 7 }, (_, index) => (first + index) % 7);
    const max = Math.max(1, ...data.heatmap.flat());
    const level = (count: number) => (count ? Math.min(HEAT_LEVELS, Math.ceil((count / max) * HEAT_LEVELS)) : 0);
    const reference = new Date(Date.UTC(2024, 0, 1));
    const weekday = formatter(this.clock.language, { weekday: "short", timeZone: "UTC" });
    const hourFormat = formatter(this.clock.language, { hour: "numeric", timeZone: "UTC" });
    const dayName = (day: number) => weekday.format(new Date(reference.getTime() + day * 86_400_000));
    const hourName = (hour: number) => hourFormat.format(new Date(reference.getTime() + hour * 3_600_000));
    return html`<div class="heatmap" role="table">
        <span></span>
        ${Array.from({ length: 24 }, (_, hour) => html`<span class="heat-hour">${hour % 6 === 0 ? hourName(hour) : ""}</span>`)}
        ${rows.map(
          (day) =>
            html`<span class="heat-day">${dayName(day)}</span> ${data.heatmap[day].map(
                (count, hour) =>
                  html`<span
                    class="heat-cell level-${level(count)}"
                    title="${dayName(day)}, ${hourName(hour)}: ${count}"
                  ></span>`,
              )}`,
        )}
      </div>
      <div class="heat-scale">
        ${this.localize("fewer")}
        ${Array.from({ length: HEAT_LEVELS + 1 }, (_, index) => html`<i class="heat-cell level-${index}"></i>`)}
        ${this.localize("more")}
      </div>`;
  }

  private _ranking(data: Statistics, slots: Map<string, number>): TemplateResult {
    const origins = data.origins.filter((origin) => origin.notifications);
    if (!origins.length) return html`<p class="stats-empty">${this.localize("no_statistics")}</p>`;
    const localize = this.localize;
    const number = new Intl.NumberFormat(this.clock.language);
    const max = origins[0].notifications;
    const label = this._rangeLabel(data);
    return html`<div class="ranking-scroll">
      <table class="ranking">
        <thead>
          <tr>
            <th>${localize("column_origin")}</th>
            <th class="number">${localize("column_count")}</th>
            <th class="number">${localize("column_trend")}</th>
            <th class="number">${localize("column_answered")}</th>
          </tr>
        </thead>
        <tbody>
          ${origins.map((origin) => {
            const name = this._name(origin, origin.key);
            const select = () => this._select({ origin: origin.key, since: data.start, until: data.end, label });
            return html`<tr
              tabindex="0"
              @click=${select}
              @keydown=${(event: KeyboardEvent) => (event.key === "Enter" || event.key === " ") && select()}
            >
              <td>
                <span class="ranking-name">
                  <i class="swatch" style="background:${colour(slots.get(origin.key) ?? 0)}"></i>
                  <span class="ranking-glyph">${originGlyph(originOf(origin.key), this.originIcons)}</span>
                  <span>${name}</span>
                </span>
                <span class="ranking-bar"
                  ><i
                    style="width:${(100 * origin.notifications) / max}%;background:${colour(slots.get(origin.key) ?? 0)}"
                  ></i
                ></span>
                ${
                  origin.bursts
                    ? html`<span class="ranking-bursts" title=${localize("bursts_hint")}
                        >${icon(mdiFlashOutline)}${
                          origin.bursts === 1
                            ? localize("bursts_one")
                            : localize("bursts_many", { count: number.format(origin.bursts) })
                        }</span
                      >`
                    : nothing
                }
              </td>
              <td class="number">${number.format(origin.notifications)}</td>
              <td class="number">${this._change(origin.notifications, origin.previous)}</td>
              <td class="number">
                ${origin.with_buttons ? `${number.format(Math.round((100 * origin.answered) / origin.with_buttons))} %` : "–"}
              </td>
            </tr>`;
          })}
        </tbody>
      </table>
    </div>`;
  }
}

export const statisticsStyles = css`
  notification-journal-statistics {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .stats-controls {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px 16px;
  }
  .stats-nav {
    display: inline-flex;
    align-items: center;
    gap: 2px;
  }
  .stats-nav .icon-button[disabled] {
    opacity: 0.35;
    cursor: default;
    background: none;
  }
  .stats-range {
    min-width: 14ch;
    text-align: center;
    font-size: 0.875rem;
    font-variant-numeric: tabular-nums;
  }
  .stats {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .stats.busy {
    opacity: 0.6;
    transition: opacity 0.2s 0.15s;
  }
  .stats-tiles {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(100%, 170px), 1fr));
    gap: 10px;
  }
  .stats-tile,
  .stats-box {
    background: var(--card-background-color);
    border-radius: var(--ha-card-border-radius, 12px);
    border: var(--ha-card-border-width, 1px) solid var(--ha-card-border-color, var(--divider-color));
    box-shadow: var(--ha-card-box-shadow, none);
    min-width: 0;
  }
  .stats-tile {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 12px 14px;
  }
  .tile-label,
  .tile-note {
    color: var(--secondary-text-color);
    font-size: 0.8rem;
  }
  .tile-value {
    font-size: 1.6rem;
    font-weight: 500;
    font-variant-numeric: tabular-nums;
  }
  .stats-box {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 14px 16px;
  }
  .stats-head {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    justify-content: space-between;
    gap: 4px 12px;
  }
  .stats-head h2 {
    margin: 0;
    font-size: 1rem;
    font-weight: 500;
  }
  .stats-head span,
  .stats-empty {
    color: var(--secondary-text-color);
    font-size: 0.8rem;
  }
  .stats-empty {
    margin: 0;
    padding: 12px 0;
    text-align: center;
  }
  .stats-columns {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(100%, 420px), 1fr));
    gap: 12px;
    align-items: start;
  }
  .legend {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 14px;
    color: var(--secondary-text-color);
    font-size: 0.8rem;
  }
  .legend span {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .swatch {
    flex: none;
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 3px;
  }
  .chart {
    position: relative;
    width: 100%;
  }
  .chart svg {
    display: block;
    width: 100%;
    height: auto;
  }
  .chart .grid {
    stroke: var(--divider-color);
  }
  .chart .baseline {
    stroke: var(--secondary-text-color);
    stroke-opacity: 0.5;
  }
  .chart .axis {
    fill: var(--secondary-text-color);
    font-size: 11px;
    font-variant-numeric: tabular-nums;
  }
  .chart .future {
    fill-opacity: 0.45;
  }
  .chart .hit {
    fill: transparent;
    cursor: pointer;
  }
  .chart .hit:hover {
    fill: color-mix(in srgb, var(--primary-text-color) 7%, transparent);
  }
  .chart-tip {
    position: absolute;
    top: 0;
    left: var(--x);
    z-index: 1;
    display: flex;
    flex-direction: column;
    gap: 3px;
    min-width: 160px;
    max-width: 300px;
    margin-left: 8px;
    padding: 8px 10px;
    border-radius: 8px;
    border: 1px solid var(--divider-color);
    background: var(--card-background-color);
    box-shadow: 0 4px 14px var(--shadow-color);
    font-size: 0.8rem;
    pointer-events: none;
  }
  .chart-tip.left {
    transform: translateX(-100%);
    margin-left: -8px;
  }
  .chart-tip span {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .chart-tip-head {
    font-weight: 500;
  }
  .chart-tip b {
    margin-left: auto;
    padding-left: 10px;
    font-weight: 500;
    font-variant-numeric: tabular-nums;
  }
  .heatmap {
    display: grid;
    grid-template-columns: auto repeat(24, minmax(0, 1fr));
    gap: 2px;
    color: var(--secondary-text-color);
    font-size: 0.7rem;
    font-variant-numeric: tabular-nums;
  }
  .heat-day {
    align-self: center;
    padding-right: 6px;
  }
  .heat-hour {
    white-space: nowrap;
  }
  .heat-cell {
    aspect-ratio: 1;
    border-radius: 3px;
    background: color-mix(in srgb, var(--primary-color) var(--level), var(--card-background-color));
  }
  .heat-cell.level-0 {
    background: color-mix(in srgb, var(--primary-text-color) 6%, var(--card-background-color));
  }
  .level-1 {
    --level: 20%;
  }
  .level-2 {
    --level: 40%;
  }
  .level-3 {
    --level: 60%;
  }
  .level-4 {
    --level: 80%;
  }
  .level-5 {
    --level: 100%;
  }
  .heat-scale {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 4px;
    color: var(--secondary-text-color);
    font-size: 0.75rem;
  }
  .heat-scale .heat-cell {
    width: 12px;
  }
  .ranking-scroll {
    overflow-x: auto;
  }
  .ranking {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.875rem;
  }
  .ranking th {
    padding: 0 6px 6px;
    border-bottom: 1px solid var(--divider-color);
    color: var(--secondary-text-color);
    font-size: 0.75rem;
    font-weight: 400;
    text-align: left;
    white-space: nowrap;
  }
  .ranking td {
    padding: 8px 6px;
    border-bottom: 1px solid var(--divider-color);
    vertical-align: top;
  }
  .ranking tr:last-child td {
    border-bottom: none;
  }
  .ranking tbody tr {
    cursor: pointer;
  }
  .ranking tbody tr:hover td,
  .ranking tbody tr:focus-visible td {
    background: color-mix(in srgb, var(--primary-text-color) 5%, transparent);
  }
  .ranking tbody tr:focus-visible {
    outline: 2px solid var(--primary-color);
    outline-offset: -2px;
  }
  .ranking .number {
    text-align: right;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }
  .ranking-name {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
  }
  .ranking-glyph {
    display: inline-flex;
    color: var(--secondary-text-color);
    --mdc-icon-size: 16px;
  }
  .ranking-glyph .icon {
    width: 16px;
    height: 16px;
  }
  .ranking-bar {
    display: block;
    height: 6px;
    margin-top: 6px;
    border-radius: 3px;
    background: color-mix(in srgb, var(--primary-text-color) 8%, transparent);
  }
  .ranking-bar i {
    display: block;
    height: 100%;
    border-radius: 3px;
  }
  .ranking-bursts {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    margin-top: 6px;
    padding: 1px 8px;
    border-radius: 10px;
    background: color-mix(in srgb, var(--warning-color) 18%, transparent);
    font-size: 0.75rem;
  }
  .ranking-bursts .icon {
    width: 13px;
    height: 13px;
    color: var(--warning-color);
  }
`;

if (!customElements.get("notification-journal-statistics")) {
  customElements.define("notification-journal-statistics", NotificationJournalStatistics);
}
