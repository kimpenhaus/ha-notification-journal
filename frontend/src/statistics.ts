import { css, html, LitElement, nothing, svg, type PropertyValues, type TemplateResult } from "lit";

import { type Clock, dayKey, formatter, numberFormatter, percentText, zoneName } from "./format";
import { icon, mdiChevronLeft, mdiChevronRight, mdiFlashOutline } from "./icons";
import { countText, type Localize } from "./localize";
import { originGlyph, originName, originOfKey } from "./record";
import { controlStyles, surface } from "./styles";
import type { HomeAssistant, OriginStatistics, Statistics, StatisticsPeriod, StatisticsSelection } from "./types";
import { errorMessage, store, stored } from "./util";

const PERIODS = ["day", "week", "month", "year"] as const satisfies readonly StatisticsPeriod[];
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

interface Column {
  start: string;
  until: string;
  segments: { slot: number; key: string; count: number }[];
  total: number;
  future: boolean;
}

/** What the view draws from one answer of the server, worked out once per answer rather than on every hover. */
interface Shape {
  data: Statistics;
  slots: Map<string, number>;
  origins: Map<string, OriginStatistics>;
  columns: Column[];
}

function shape(data: Statistics): Shape {
  const slots = new Map(data.origins.slice(0, COLOURED).map((origin, index) => [origin.key, index + 1]));
  const now = Date.now();
  const columns = data.buckets.map((bucket, index): Column => {
    const stacks = new Map<number, { key: string; count: number }>();
    for (const [key, count] of Object.entries(bucket.counts)) {
      const slot = slots.get(key) ?? 0;
      stacks.set(slot, { key: slot ? key : OTHER, count: (stacks.get(slot)?.count ?? 0) + count });
    }
    const segments = [...stacks.entries()]
      .sort(([left], [right]) => (left || COLOURED + 1) - (right || COLOURED + 1))
      .map(([slot, stack]) => ({ slot, ...stack }));
    return {
      start: bucket.start,
      until: data.buckets[index + 1]?.start ?? data.end,
      segments,
      total: segments.reduce((sum, segment) => sum + segment.count, 0),
      future: Date.parse(bucket.start) > now,
    };
  });
  return { data, slots, origins: new Map(data.origins.map((origin) => [origin.key, origin])), columns };
}

export class NotificationJournalStatistics extends LitElement {
  static override properties = {
    hass: { attribute: false },
    localize: { attribute: false },
    clock: { attribute: false },
    originIcons: { attribute: false },
    _period: { state: true },
    _offset: { state: true },
    _shape: { state: true },
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
  declare _shape: Shape | undefined;
  declare _error: string | undefined;
  declare _loading: boolean;
  declare _width: number;
  declare _hover: number | undefined;

  private _request = 0;
  private _resize?: ResizeObserver;
  private _observed?: Element;

  constructor() {
    super();
    const period = stored(PERIOD_KEY);
    this._period = PERIODS.find((known) => known === period) ?? "week";
    this._offset = 0;
    this._loading = false;
    this._width = 0;
  }

  override connectedCallback(): void {
    super.connectedCallback();
    void this.refresh();
  }

  override disconnectedCallback(): void {
    super.disconnectedCallback();
    this._resize?.disconnect();
    this._resize = undefined;
    this._observed = undefined;
  }

  protected override updated(changed: PropertyValues): void {
    super.updated(changed);
    const chart = this.renderRoot.querySelector(".chart");
    if (!chart || chart === this._observed) return;
    this._resize ??= new ResizeObserver(([entry]) => {
      const width = Math.round(entry.contentRect.width);
      if (width !== this._width) this._width = width;
    });
    this._resize.disconnect();
    this._resize.observe(chart);
    this._observed = chart;
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
        time_zone: zoneName(this.clock),
      });
      if (request !== this._request) return;
      this._shape = shape(data);
      this._error = undefined;
    } catch (error) {
      if (request !== this._request) return;
      this._error = this.localize("stats_failed", { message: errorMessage(error) });
    } finally {
      if (request === this._request) this._loading = false;
    }
  }

  private _show(period: StatisticsPeriod, offset: number): void {
    if (period !== this._period) store(PERIOD_KEY, period);
    this._period = period;
    this._offset = offset;
    this._hover = undefined;
    void this.refresh();
  }

  private _select(range: StatisticsSelection["range"], origin?: StatisticsSelection["origin"]): void {
    this.dispatchEvent(
      new CustomEvent<StatisticsSelection>("statistics-select", {
        detail: { range, origin, keptSince: this._shape?.data.kept_since ?? null },
        bubbles: true,
        composed: true,
      }),
    );
  }

  private _format(iso: string, options: Intl.DateTimeFormatOptions): string {
    return formatter(this.clock.language, { ...options, timeZone: this.clock.timeZone }).format(new Date(iso));
  }

  private _number(value: number): string {
    return numberFormatter(this.clock.language).format(value);
  }

  private _rangeLabel(data: Statistics): string {
    switch (data.period) {
      case "day":
        return this._format(data.start, { weekday: "short", day: "numeric", month: "long", year: "numeric" });
      case "week": {
        const range = formatter(this.clock.language, {
          day: "numeric",
          month: "short",
          timeZone: this.clock.timeZone,
        }).formatRange(new Date(data.start), new Date(Date.parse(data.end) - 1));
        if (firstWeekday(this.hass) !== 0) return range;
        const [year, month, day] = dayKey(this.clock, data.start).split("-").map(Number);
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
    if (period === "day") {
      return this._format(iso, { weekday: "short", day: "numeric", month: "short", hour: "numeric" });
    }
    if (period === "year") return this._format(iso, { month: "long", year: "numeric" });
    return this._format(iso, { weekday: "long", day: "numeric", month: "long" });
  }

  private _name(key: string): string {
    if (key === OTHER) return this.localize("other_origins");
    return originName(this.localize, key, this._shape?.origins.get(key)?.name ?? null);
  }

  private _change(comparable: boolean, current: number, previous: number): string {
    if (!comparable) return "–";
    if (!previous) return current ? this.localize("trend_new") : "±0";
    const change = Math.round((100 * (current - previous)) / previous);
    if (change === 0) return "±0 %";
    return `${change > 0 ? "↑ +" : "↓ −"}${this._number(Math.abs(change))} %`;
  }

  override render(): TemplateResult {
    const localize = this.localize;
    const data = this._shape?.data;
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
          <span class="stats-range">${data?.period === this._period ? this._rangeLabel(data) : ""}</span>
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
          : this._shape
            ? html`<div class="stats ${this._loading ? "busy" : ""}">${this._content(this._shape)}</div>`
            : html`<div class="empty"><p>${localize("loading")}</p></div>`
      }
    `;
  }

  private _content(shape: Shape): TemplateResult {
    const localize = this.localize;
    return html`
      ${this._tiles(shape.data)}
      <section class="stats-box">
        <div class="stats-head">
          <h2>${localize("history")}</h2>
          <span>${localize("history_hint")}</span>
        </div>
        ${this._legend(shape)} ${this._chart(shape)}
      </section>
      <div class="stats-columns">
        <section class="stats-box">
          <div class="stats-head">
            <h2>${localize("when")}</h2>
            <span>${localize("when_hint")}</span>
          </div>
          ${this._heatmap(shape.data)}
        </section>
        <section class="stats-box">
          <div class="stats-head">
            <h2>${localize("who")}</h2>
            <span>${localize("who_hint")}</span>
          </div>
          ${this._ranking(shape)}
        </section>
      </div>
    `;
  }

  /** The name of the origin with the most of a field, if any has some. */
  private _top(data: Statistics, field: "night" | "bursts" | "failed"): string | undefined {
    const top = data.origins.reduce<OriginStatistics | undefined>(
      (best, origin) => (origin[field] > (best?.[field] ?? 0) ? origin : best),
      undefined,
    );
    return top && this._name(top.key);
  }

  private _tiles(data: Statistics): TemplateResult {
    const localize = this.localize;
    const totals = data.totals;
    const night = this._top(data, "night");
    const bursts = this._top(data, "bursts");
    const failed = this._top(data, "failed");
    const compared = (current: number, previous: number) =>
      data.comparable
        ? localize(`compare_${data.period}`, { change: this._change(true, current, previous) })
        : localize("no_comparison");
    const tile = (label: string, value: string, note: string, title?: string) =>
      html`<div class="stats-tile" title=${title ?? nothing}>
        <span class="tile-label">${label}</span>
        <span class="tile-value">${value}</span>
        <span class="tile-note">${note}</span>
      </div>`;
    return html`<div class="stats-tiles">
      ${tile(
        localize("tile_notifications"),
        this._number(totals.notifications),
        compared(totals.notifications, totals.previous),
      )}
      ${tile(
        localize("tile_answered"),
        percentText(this.clock.language, totals.answered, totals.with_buttons),
        totals.with_buttons
          ? localize("answered_of", {
              answered: this._number(totals.answered),
              total: this._number(totals.with_buttons),
            })
          : localize("no_buttons"),
      )}
      ${tile(
        localize("tile_night"),
        this._number(totals.night),
        night ? localize("mostly", { name: night }) : localize("quiet"),
      )}
      ${tile(
        localize("tile_bursts"),
        this._number(totals.bursts),
        bursts ? localize("mostly", { name: bursts }) : localize("bursts_hint"),
        localize("bursts_hint"),
      )}
      ${tile(
        localize("tile_failed"),
        this._number(totals.failed),
        compared(totals.failed, totals.previous_failed),
        failed ? localize("mostly", { name: failed }) : undefined,
      )}
    </div>`;
  }

  private _legend({ data, slots }: Shape): TemplateResult {
    if (!data.totals.notifications) return html`<p class="stats-empty">${this.localize("no_statistics")}</p>`;
    const sent = data.origins.filter((origin) => origin.notifications);
    const other = sent.some((origin) => !slots.has(origin.key));
    return html`<div class="legend">
      ${sent
        .filter((origin) => slots.has(origin.key))
        .map(
          (origin) =>
            html`<span
              ><i class="swatch" style="background:${colour(slots.get(origin.key)!)}"></i
              >${this._name(origin.key)}</span
            >`,
        )}
      ${other ? html`<span><i class="swatch" style="background:${colour(0)}"></i>${this._name(OTHER)}</span>` : nothing}
    </div>`;
  }

  private _chart({ data, columns }: Shape): TemplateResult {
    const width = Math.max(this._width, 280);
    const max = Math.max(0, ...columns.map((column) => column.total));
    const step = niceStep(max);
    const top = Math.max(step, Math.ceil(max / step) * step);
    const plotHeight = CHART_HEIGHT - LABEL_HEIGHT - 8;
    const columnWidth = (width - AXIS_WIDTH) / columns.length;
    const barWidth = Math.max(3, Math.min(40, columnWidth * 0.62));
    const y = (value: number) => 8 + plotHeight - (value / top) * plotHeight;
    const ticks: number[] = [];
    for (let value = 0; value <= top; value += step) ticks.push(value);
    const hover = this._hover;
    const hovered = hover !== undefined ? columns[hover] : undefined;
    const left = hover !== undefined && hover > columns.length / 2;
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
              class="chart-tip ${left ? "left" : ""}"
              style="--x:${AXIS_WIDTH + columnWidth * (hover! + (left ? 0 : 1))}px"
            >
              <span class="chart-tip-head"
                >${this._bucketTitle(data.period, hovered.start)}<b>${hovered.total}</b></span
              >
              ${[...hovered.segments]
                .reverse()
                .map(
                  (segment) =>
                    html`<span
                      ><i class="swatch" style="background:${colour(segment.slot)}"></i>${this._name(segment.key)}<b
                        >${segment.count}</b
                      ></span
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
    const reference = Date.UTC(2024, 0, 1);
    const weekday = formatter(this.clock.language, { weekday: "short", timeZone: "UTC" });
    const hourFormat = formatter(this.clock.language, { hour: "numeric", timeZone: "UTC" });
    const dayName = (day: number) => weekday.format(new Date(reference + day * 86_400_000));
    const hourName = (hour: number) => hourFormat.format(new Date(reference + hour * 3_600_000));
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

  private _ranking({ data, slots }: Shape): TemplateResult {
    const origins = data.origins.filter((origin) => origin.notifications);
    if (!origins.length) return html`<p class="stats-empty">${this.localize("no_statistics")}</p>`;
    const localize = this.localize;
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
            const name = this._name(origin.key);
            const shade = colour(slots.get(origin.key) ?? 0);
            const select = () => this._select({ since: data.start, until: data.end, label }, { key: origin.key, name });
            return html`<tr
              tabindex="0"
              @click=${select}
              @keydown=${(event: KeyboardEvent) => (event.key === "Enter" || event.key === " ") && select()}
            >
              <td>
                <span class="ranking-name">
                  <i class="swatch" style="background:${shade}"></i>
                  <span class="ranking-glyph">${originGlyph(originOfKey(origin.key), this.originIcons)}</span>
                  <span>${name}</span>
                </span>
                <span class="ranking-bar"
                  ><i style="width:${(100 * origin.notifications) / max}%;background:${shade}"></i
                ></span>
                ${
                  origin.bursts
                    ? html`<span class="ranking-bursts" title=${localize("bursts_hint")}
                        >${icon(mdiFlashOutline)}${countText(localize, origin.bursts, "bursts_one", "bursts_many")}</span
                      >`
                    : nothing
                }
              </td>
              <td class="number">${this._number(origin.notifications)}</td>
              <td class="number">${this._change(data.comparable, origin.notifications, origin.previous)}</td>
              <td class="number">${percentText(this.clock.language, origin.answered, origin.with_buttons)}</td>
            </tr>`;
          })}
        </tbody>
      </table>
    </div>`;
  }

  static override styles = [
    controlStyles,
    css`
      :host {
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
      .stats-tiles {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(min(100%, 170px), 1fr));
        gap: 10px;
      }
      .stats-tile,
      .stats-box {
        ${surface}
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
        box-shadow: var(--ha-card-box-shadow, none);
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
    `,
  ];
}

if (!customElements.get("notification-journal-statistics")) {
  customElements.define("notification-journal-statistics", NotificationJournalStatistics);
}
