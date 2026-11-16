import { css, html, LitElement, nothing, type PropertyValues, type TemplateResult } from "lit";
import { ref } from "lit/directives/ref.js";

import { channelLabel, type Clock, dateTimeText, dayKey, initials, shortDateTimeText, timeText } from "./format";
import {
  icon,
  mdiAccountGroupOutline,
  mdiAccountOutline,
  mdiAccountMultipleOutline,
  mdiAlertCircleOutline,
  mdiBellCheckOutline,
  mdiBellOutline,
  mdiBullhornOutline,
  mdiCellphone,
  mdiChatOutline,
  mdiCheck,
  mdiCheckAll,
  mdiChevronDown,
  mdiCheckboxBlankCircleOutline,
  mdiCheckCircle,
  mdiHelpCircleOutline,
  mdiHomeAssistant,
  mdiImageOffOutline,
  mdiOpenInNew,
  mdiPlay,
  mdiPuzzleOutline,
  mdiRobotOutline,
  mdiScriptTextOutline,
  mdiSendCheckOutline,
  mdiSpeaker,
  mdiSwapHorizontal,
  mdiTagOutline,
  mdiVideoOutline,
  mdiVolumeHigh,
} from "./icons";
import { countText, type Localize } from "./localize";
import { followInternal, inline } from "./markdown";
import { appData, fileName, loadable, type Media, notificationMedia, notificationTag, type Signer } from "./media";
import { surface } from "./styles";
import type { Answer, NotificationRecord, Origin, OriginKind, Recipient, Status } from "./types";

const BELL = "persistent_notification";
const SPEECH = "speech";
const STATUS_ICONS: Record<Status, string> = {
  sent: mdiSendCheckOutline,
  delivered: mdiCheckAll,
  failed: mdiAlertCircleOutline,
  dismissed: mdiBellCheckOutline,
  replaced: mdiSwapHorizontal,
};

const ORIGIN_ICONS: Record<OriginKind, string> = {
  automation: mdiRobotOutline,
  script: mdiScriptTextOutline,
  user: mdiAccountOutline,
  integration: mdiPuzzleOutline,
  system: mdiHomeAssistant,
  unknown: mdiHelpCircleOutline,
};

/** The icon of an origin: the automation's or script's own icon if it has one, else the one of its kind. */
/** The origin a key (`origin_key` in the store) stands for, as far as the key tells. */
export function originOfKey(key: string): Origin {
  const domain = key.slice(0, key.indexOf("."));
  const kind = (
    domain === "automation" || domain === "script" || domain === "integration" ? domain : key
  ) as OriginKind;
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

/** The name of an origin by its key; Home Assistant, a user by hand and an unknown origin have none of their own. */
export function originName(localize: Localize, key: string, name: string | null): string {
  if (name) return name;
  if (key === "user") return localize("origin_by_hand");
  if (key === "system") return localize("origin_system");
  if (key === "unknown") return localize("origin_unknown");
  return key;
}

export function originGlyph(origin: Origin, originIcons: Map<string, string>): TemplateResult {
  const own = origin.entity_id ? originIcons.get(origin.entity_id) : undefined;
  return own && customElements.get("ha-icon")
    ? html`<ha-icon .icon=${own}></ha-icon>`
    : icon(ORIGIN_ICONS[origin.kind]);
}

const DEVICE_ICONS: Partial<Record<Recipient["kind"], string>> = {
  channel: mdiCellphone,
  speaker: mdiSpeaker,
  chat: mdiChatOutline,
};

interface Button {
  action: string;
  title: string;
}

/** The buttons a notification offered in the Companion app (`data.actions`). */
function offeredButtons(record: NotificationRecord): Button[] {
  const actions = appData(record).actions;
  if (!Array.isArray(actions)) return [];
  return actions.flatMap((item) => {
    if (!item || typeof item !== "object") return [];
    const { action, title } = item as Record<string, unknown>;
    return typeof action === "string" ? [{ action, title: typeof title === "string" ? title : action }] : [];
  });
}

function personAvatar(name: string, picture: string | null): TemplateResult {
  return picture
    ? html`<img class="avatar" src=${picture} alt="" loading="lazy" />`
    : html`<span class="avatar initials">${initials(name)}</span>`;
}

export function recipientChip(recipient: Recipient): TemplateResult {
  let avatar: TemplateResult;
  if (recipient.kind === "person") {
    avatar = personAvatar(recipient.name, recipient.picture);
  } else {
    avatar = html`<span class="avatar device">${icon(DEVICE_ICONS[recipient.kind] ?? mdiBellOutline)}</span>`;
  }
  return html`<span class="chip recipient ${recipient.kind}" title=${recipient.id}>${avatar}${recipient.name}</span>`;
}

/** Loads the first frame of a video only once its card is on the screen. */
const frames = new IntersectionObserver((entries) => {
  for (const entry of entries) {
    if (!entry.isIntersecting) continue;
    const video = entry.target as HTMLVideoElement;
    frames.unobserve(video);
    if (video.dataset.src) video.src = video.dataset.src;
  }
});

export class NotificationJournalRecord extends LitElement {
  static override properties = {
    record: { attribute: false },
    localize: { attribute: false },
    clock: { attribute: false },
    admin: { type: Boolean },
    userNames: { attribute: false },
    originIcons: { attribute: false },
    showDate: { type: Boolean },
    _details: { state: true },
    _calls: { state: true },
    _playing: { state: true },
    _failed: { state: true },
    _sources: { state: true },
    sign: { attribute: false },
    selectable: { type: Boolean },
    selected: { type: Boolean },
  };

  declare record: NotificationRecord;
  declare localize: Localize;
  declare clock: Clock;
  declare admin: boolean;
  declare userNames: Map<string, string>;
  declare originIcons: Map<string, string>;
  declare showDate: boolean;
  declare _details: boolean;
  declare _calls: boolean;
  declare _playing: boolean;
  declare _failed: ReadonlySet<string>;
  declare _sources: ReadonlyMap<string, string>;
  declare sign: Signer | undefined;
  private _found: Media = {};
  private _frame: Element | undefined;
  declare selectable: boolean;
  declare selected: boolean;

  constructor() {
    super();
    this.admin = false;
    this.userNames = new Map();
    this.originIcons = new Map();
    this.showDate = false;
    this._details = false;
    this._calls = false;
    this._playing = false;
    this._failed = new Set();
    this._sources = new Map();
    this.selectable = false;
    this.selected = false;
  }

  override render(): TemplateResult {
    const record = this.record;
    const localize = this.localize;
    const open = record.source === BELL && record.status === "sent";
    const statusText = open ? localize("status_open") : localize(`status_${record.status}`);
    const statusIcon = open
      ? mdiBellOutline
      : record.source === SPEECH && record.status === "sent"
        ? mdiBullhornOutline
        : STATUS_ICONS[record.status];
    const title = record.title || localize(record.source === SPEECH ? "untitled_speech" : "untitled");
    const answered = record.status === "sent" && record.answers.length > 0;
    return html`
      <article
        class="card ${record.status} ${answered ? "answered" : ""} ${this.selectable ? "selectable" : ""} ${
          this.selected ? "selected" : ""
        }"
        @click=${this._clicked}
      >
        <div class="side">
          ${
            this.selectable
              ? html`<div
                  class="check"
                  role="checkbox"
                  aria-checked=${this.selected ? "true" : "false"}
                  aria-label=${title}
                >
                  ${icon(this.selected ? mdiCheckCircle : mdiCheckboxBlankCircleOutline)}
                </div>`
              : html`<div class="status" title=${statusText}>${icon(statusIcon, statusText)}</div>`
          }
        </div>
        <div class="body">
          <header>
            <h3>${title}</h3>
            ${
              answered
                ? html`<span class="badge">${localize("status_answered")}</span>`
                : record.status === "sent"
                  ? nothing
                  : html`<span class="badge">${statusText}</span>`
            }
            <time datetime=${record.time} title=${dateTimeText(this.clock, record.time)}
              >${this.showDate ? shortDateTimeText(this.clock, record.time) : timeText(this.clock, record.time)}</time
            >
          </header>
          <div class="indent">
            ${this._message()} ${this._statusNote(statusText)}
            ${record.error ? html`<p class="error">${icon(mdiAlertCircleOutline)}${record.error}</p>` : nothing}
            ${this._media()} ${this._buttons()}
            <div class="chips">${this._origin()} ${this._route()} ${this._tag()}</div>
            ${this._calls ? this._innerCalls() : nothing} ${this._details ? this._detailList() : nothing}
          </div>
          <button
            class="more ${this._details ? "open" : ""}"
            aria-expanded=${this._details ? "true" : "false"}
            @click=${() => (this._details = !this._details)}
          >
            ${localize(this._details ? "hide_details" : "show_details")}${icon(mdiChevronDown)}
          </button>
        </div>
      </article>
    `;
  }

  protected override willUpdate(changed: PropertyValues): void {
    super.willUpdate(changed);
    if (!changed.has("record") && !changed.has("sign")) return;
    const media = notificationMedia(this.record);
    const found = this._found;
    if (
      changed.has("sign") ||
      media.image !== found.image ||
      media.video !== found.video ||
      media.audio !== found.audio
    ) {
      this._found = media;
      this._resolve(media);
    }
  }

  private _fail(address: string): void {
    this._failed = new Set([...this._failed, address]);
  }

  /** Resolves where to load the media from, signing paths on this Home Assistant. */
  private _resolve(media: Media): void {
    const sources = new Map<string, string>();
    const pending: Promise<[string, string]>[] = [];
    for (const address of [media.image, media.video, media.audio]) {
      if (!address) continue;
      const source = loadable(address, this.sign);
      if (typeof source === "string") sources.set(address, source);
      else pending.push(source.then((path) => [address, path]));
    }
    this._sources = sources;
    if (!pending.length) return;
    void Promise.all(pending).then((entries) => {
      if (this._found === media) this._sources = new Map([...sources, ...entries]);
    });
  }

  private _observeFrame(video: Element | undefined): void {
    if (this._frame) frames.unobserve(this._frame);
    this._frame = video;
    if (video) frames.observe(video);
  }

  private _usable(address: string | undefined): string | undefined {
    return address && !this._failed.has(address) ? address : undefined;
  }

  /** An image, or a video with the image or its first frame as preview; a link for audio and what cannot load. */
  private _media(): TemplateResult | typeof nothing {
    const { image, video, audio } = this._found;
    if (!image && !video && !audio) return nothing;
    const localize = this.localize;
    const poster = this._usable(image);
    const playable = this._usable(video);
    return html`<div class="media">
      ${
        playable
          ? this._video(playable, poster)
          : html`${
              poster
                ? this._image(poster)
                : image
                  ? this._mediaLink(image, mdiImageOffOutline, localize("open_image"), true)
                  : nothing
            }
            ${video ? this._mediaLink(video, mdiVideoOutline, localize("play_video"), true) : nothing}`
      }
      ${audio ? this._mediaLink(audio, mdiVolumeHigh, localize("play_audio")) : nothing}
    </div>`;
  }

  private _mediaLink(address: string, glyph: string, label: string, unavailable = false): TemplateResult {
    const note = unavailable ? `${this.localize("media_unavailable")} · ` : "";
    return html`<a
      class="chip link media-link"
      href=${this._sources.get(address) ?? address}
      target="_blank"
      rel="noopener noreferrer"
      >${icon(glyph)}${label}<span class="media-name">· ${note}${fileName(address)}</span></a
    >`;
  }

  private _image(address: string): TemplateResult | typeof nothing {
    const source = this._sources.get(address);
    if (!source) return nothing;
    return html`<a
      class="preview"
      href=${source}
      target="_blank"
      rel="noopener noreferrer"
      title=${this.localize("open_image")}
      ><img src=${source} alt="" loading="lazy" @error=${() => this._fail(address)}
    /></a>`;
  }

  private _video(address: string, poster: string | undefined): TemplateResult | typeof nothing {
    const source = this._sources.get(address);
    if (!source) return nothing;
    const posterSource = poster ? this._sources.get(poster) : undefined;
    if (this._playing) {
      return html`<video
        class="player"
        src=${source}
        poster=${posterSource ?? nothing}
        controls
        autoplay
        playsinline
        @error=${() => {
          this._playing = false;
          this._fail(address);
        }}
      ></video>`;
    }
    return html`<button
      class="preview video"
      title=${this.localize("play_video")}
      @click=${() => (this._playing = true)}
    >
      ${
        poster
          ? html`<img src=${posterSource ?? nothing} alt="" loading="lazy" @error=${() => this._fail(poster)} />`
          : html`<video
              class="frame"
              data-src="${source}#t=0.1"
              preload="metadata"
              muted
              playsinline
              ${ref((element) => this._observeFrame(element))}
              @error=${() => this._fail(address)}
            ></video>`
      }
      <span class="play">${icon(mdiPlay)}</span>
      <span class="caption">${fileName(address)}</span>
    </button>`;
  }

  private _tag(): TemplateResult | typeof nothing {
    const tag = notificationTag(this.record);
    if (!tag) return nothing;
    return html`<button
      class="chip tag"
      title=${this.localize("filter_by_tag")}
      @click=${() =>
        this.dispatchEvent(new CustomEvent("notification-tag", { detail: { tag }, bubbles: true, composed: true }))}
    >
      ${icon(mdiTagOutline)}${tag}
    </button>`;
  }

  private _clicked(event: MouseEvent): void {
    if (!this.selectable) return;
    const interactive = event
      .composedPath()
      .some((target) => target instanceof Element && target.matches("a, button, video, input, select, textarea"));
    if (interactive) return;
    this.dispatchEvent(
      new CustomEvent("notification-select", { detail: { id: this.record.id }, bubbles: true, composed: true }),
    );
  }

  private _statusNote(statusText: string): TemplateResult | typeof nothing {
    const record = this.record;
    if (!record.status_time) return nothing;
    const time = shortDateTimeText(this.clock, record.status_time);
    const name = record.status_by ? this._originName(record.status_by) : undefined;
    const values = { status: statusText, time, name: name ?? "" };
    const text = this.localize(name ? "status_note_by" : "status_note", values);
    return html`<p class="status-note">${text}</p>`;
  }

  private _message(): TemplateResult | typeof nothing {
    const record = this.record;
    if (!record.message) return nothing;
    const content = record.source === BELL ? inline(record.message) : record.message;
    return html`<p class="message ${this._details ? "" : "clamp"}">${content}</p>`;
  }

  private _buttons(): TemplateResult | typeof nothing {
    const record = this.record;
    const buttons = offeredButtons(record);
    if (!buttons.length) return nothing;
    const answers = record.answers;
    const single = answers.length === 1 ? answers[0] : undefined;
    return html`<div class="actions">
      <div class="buttons">
        ${buttons.map((button) => {
          const chosen = answers.filter((answer) => answer.action === button.action);
          if (!chosen.length) return html`<span class="button">${button.title}</span>`;
          const by = single ? `${this._answerer(single).name}, ${this._answerTime(single)}` : String(chosen.length);
          return html`<span class="button chosen"
            >${icon(mdiCheck)}${button.title}<span class="by">· ${by}</span></span
          >`;
        })}
      </div>
      ${single?.reply_text ? this._reply(single) : nothing}
      ${
        answers.length > 1
          ? html`<ul class="answers">
              ${answers.map((answer) => this._answerRow(answer, buttons))}
            </ul>`
          : nothing
      }
    </div>`;
  }

  private _answerer(answer: Answer): { id: string; name: string; picture: string | null } {
    const record = this.record;
    const person = answer.user_id
      ? [...record.recipients, ...record.inner_calls.flatMap((call) => call.recipients)].find(
          (recipient) => recipient.user_id === answer.user_id,
        )
      : undefined;
    if (person) return person;
    const id = answer.user_id ?? "";
    return {
      id,
      name: (answer.user_id && this.userNames.get(answer.user_id)) || this.localize("someone"),
      picture: null,
    };
  }

  private _answerTime(answer: Answer): string {
    const sameDay = dayKey(this.clock, answer.time) === dayKey(this.clock, this.record.time);
    return sameDay ? timeText(this.clock, answer.time) : shortDateTimeText(this.clock, answer.time);
  }

  private _reply(answer: Answer): TemplateResult {
    const who = this._answerer(answer);
    return html`<div class="reply">
      ${personAvatar(who.name, who.picture)}
      <p>${answer.reply_text}<span class="by">${who.name}, ${this._answerTime(answer)}</span></p>
    </div>`;
  }

  private _answerRow(answer: Answer, buttons: Button[]): TemplateResult {
    const who = this._answerer(answer);
    const title = buttons.find((button) => button.action === answer.action)?.title ?? answer.action;
    return html`<li>
      ${personAvatar(who.name, who.picture)}
      <span>${who.name}: <b>${title}</b>${answer.reply_text ? html` „${answer.reply_text}“` : nothing}</span>
      <span class="by">${this._answerTime(answer)}</span>
    </li>`;
  }

  private _originName(origin: Origin): string | undefined {
    if (origin.kind === "automation" || origin.kind === "script") return origin.name ?? origin.entity_id ?? undefined;
    if (origin.kind === "user") return origin.user_id ? this.userNames.get(origin.user_id) : undefined;
    if (origin.kind === "integration") return origin.name ?? origin.integration ?? undefined;
    if (origin.kind === "system") return this.localize("origin_system");
    return undefined;
  }

  private _origin(): TemplateResult {
    const origin = this.record.origin;
    const localize = this.localize;
    if (origin.kind === "automation" || origin.kind === "script") {
      const label = html`${originGlyph(origin, this.originIcons)}
        <span>${origin.name ?? origin.entity_id ?? localize(`origin_${origin.kind}`)}</span>`;
      const path = this.record.trace_path;
      if (this.admin && path) {
        return html`<a class="chip origin link" href=${path} title=${localize("open_trace")} @click=${followInternal}
          >${label}${icon(mdiOpenInNew)}</a
        >`;
      }
      return html`<span class="chip origin" title=${localize(`origin_${origin.kind}`)}>${label}</span>`;
    }
    if (origin.kind === "user") {
      const name = origin.user_id ? this.userNames.get(origin.user_id) : undefined;
      return html`<span class="chip origin"
        >${originGlyph(origin, this.originIcons)}${name ? localize("origin_user", { name }) : localize("origin_user_unknown")}</span
      >`;
    }
    if (origin.kind === "integration") {
      return html`<span class="chip origin" title=${localize("origin_integration")}
        >${originGlyph(origin, this.originIcons)}<span>${origin.name ?? origin.integration}</span></span
      >`;
    }
    if (origin.kind === "system") {
      return html`<span class="chip origin"
        >${originGlyph(origin, this.originIcons)}${localize("origin_system")}</span
      >`;
    }
    return html`<span class="chip origin muted"
      >${originGlyph(origin, this.originIcons)}${localize("origin_unknown")}</span
    >`;
  }

  private _route(): TemplateResult {
    const record = this.record;
    if (!record.group) {
      if (record.recipients.length) {
        return html`${record.recipients.map((recipient) =>
          recipient.kind === "everyone"
            ? html`<span class="chip recipient everyone" title=${this.localize("everyone_hint")}
                ><span class="avatar device">${icon(mdiAccountMultipleOutline)}</span>${this.localize("everyone")}</span
              >`
            : recipientChip(recipient),
        )}`;
      }
      return html`<span class="chip route" title=${this.localize("channel")}
        >${icon(mdiBellOutline)}${channelLabel(record.channel)}</span
      >`;
    }
    const count = record.inner_calls.length;
    return html`<button
      class="chip route group ${this._calls ? "open" : ""}"
      aria-expanded=${this._calls ? "true" : "false"}
      title=${countText(this.localize, count, "inner_calls_one", "inner_calls")}
      @click=${() => (this._calls = !this._calls)}
    >
      ${icon(mdiAccountGroupOutline)}${channelLabel(record.group)}<span class="count">${count}</span>${icon(
        mdiChevronDown,
      )}
    </button>`;
  }

  private _innerCalls(): TemplateResult {
    const calls = this.record.inner_calls;
    return html`<section class="calls">
      <h4>${countText(this.localize, calls.length, "inner_calls_one", "inner_calls")}</h4>
      <ul>
        ${calls.map(
          (call) =>
            html`<li>
              <span class="call-channel">${icon(mdiCellphone)}${channelLabel(call.channel)}</span>
              <span class="chips"
                >${call.recipients.filter((recipient) => recipient.id !== call.channel).map(recipientChip)}</span
              >
            </li>`,
        )}
      </ul>
    </section>`;
  }

  private _detailList(): TemplateResult {
    const record = this.record;
    const localize = this.localize;
    const rows: [string, unknown][] = [
      [localize("time"), dateTimeText(this.clock, record.time)],
      [localize("source"), record.source],
      [localize("channel"), record.channel],
      [localize("group"), record.group],
      [localize("notification_id"), record.source_ref ? html`<code>${record.source_ref}</code>` : null],
      [localize("context"), html`<code>${record.context_id}</code>`],
      [localize("recorded"), record.origin.imported ? localize("imported") : null],
    ];
    return html`<section class="details">
      <dl>
        ${rows
          .filter(([, value]) => value)
          .map(
            ([label, value]) =>
              html`<dt>${label}</dt>
                <dd>${value}</dd>`,
          )}
      </dl>
      ${
        record.data
          ? html`<h4>${localize("data")}</h4>
              <pre>${JSON.stringify(record.data, null, 2)}</pre>`
          : nothing
      }
    </section>`;
  }

  static override styles = css`
    :host {
      display: block;
    }
    .card {
      --status-color: var(--info-color);
      display: flex;
      gap: 14px;
      padding: 14px 16px 6px;
      ${surface}
      border-left: 4px solid var(--status-color);
    }
    .card.delivered,
    .card.answered {
      --status-color: var(--success-color);
    }
    .card.failed {
      --status-color: var(--error-color);
    }
    .card.dismissed,
    .card.replaced {
      --status-color: var(--secondary-text-color);
    }
    .message a {
      color: var(--primary-color);
    }
    .message code {
      font-family: var(--ha-font-family-code);
      font-size: 0.9em;
      padding: 0 4px;
      border-radius: 4px;
      background: var(--secondary-background-color);
    }
    .status-note {
      margin: 6px 0 0;
      font-size: 0.85rem;
      color: var(--secondary-text-color);
    }
    .side {
      flex: none;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding-bottom: 8px;
    }
    .card.selectable {
      cursor: pointer;
      user-select: none;
    }
    .card.selected {
      border-color: var(--primary-color);
      background: color-mix(in srgb, var(--primary-color) 8%, var(--card-background-color));
    }
    .check {
      display: grid;
      place-items: center;
      width: 36px;
      height: 36px;
      color: var(--secondary-text-color);
    }
    .card.selected .check {
      color: var(--primary-color);
    }
    .check .icon {
      width: 26px;
      height: 26px;
    }
    .status {
      flex: none;
      display: grid;
      place-items: center;
      width: 36px;
      height: 36px;
      border-radius: 50%;
      color: var(--status-color);
      background: color-mix(in srgb, var(--status-color) 14%, transparent);
    }
    .icon {
      width: 18px;
      height: 18px;
      fill: currentColor;
      flex: none;
    }
    .status .icon {
      width: 20px;
      height: 20px;
    }
    .body {
      flex: 1;
      min-width: 0;
    }
    header {
      display: flex;
      align-items: baseline;
      gap: 8px;
    }
    h3 {
      flex: 1;
      margin: 0;
      font-size: 1.12rem;
      font-weight: 500;
      line-height: 1.35;
      color: var(--primary-text-color);
      overflow-wrap: anywhere;
    }
    time {
      flex: none;
      font-size: 0.85rem;
      color: var(--secondary-text-color);
      font-variant-numeric: tabular-nums;
    }
    .badge {
      flex: none;
      font-size: 0.72rem;
      font-weight: 500;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      padding: 2px 8px;
      border-radius: 10px;
      color: var(--status-color);
      background: color-mix(in srgb, var(--status-color) 14%, transparent);
    }
    .message {
      margin: 8px 0 0;
      color: var(--primary-text-color);
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      line-height: 1.45;
    }
    .message.clamp {
      display: -webkit-box;
      -webkit-line-clamp: 4;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }
    .error {
      display: flex;
      gap: 6px;
      align-items: flex-start;
      margin: 8px 0 0;
      padding: 8px 10px;
      border-radius: 8px;
      color: var(--error-color);
      background: color-mix(in srgb, var(--error-color) 10%, transparent);
      overflow-wrap: anywhere;
    }
    .indent {
      padding-left: 14px;
    }
    .actions {
      display: grid;
      gap: 8px;
      margin-top: 12px;
    }
    .buttons {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }
    .button {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 4px 10px;
      border-radius: 8px;
      border: 1px solid var(--divider-color);
      color: var(--secondary-text-color);
      font-size: 0.85rem;
      overflow-wrap: anywhere;
    }
    .button.chosen {
      --answer-color: var(--success-color);
      border-color: var(--answer-color);
      color: var(--answer-color);
      background: color-mix(in srgb, var(--answer-color) 12%, transparent);
      font-weight: 500;
    }
    .button.chosen .icon {
      width: 16px;
      height: 16px;
    }
    .by {
      font-weight: 400;
      font-size: 0.8rem;
      color: var(--secondary-text-color);
    }
    .reply {
      display: flex;
      gap: 8px;
      align-items: flex-start;
      padding: 8px 10px;
      border-radius: 10px;
      background: var(--secondary-background-color);
    }
    .reply p {
      margin: 0;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
    .reply .by {
      display: block;
      margin-top: 2px;
    }
    .answers {
      display: grid;
      gap: 6px;
      margin: 0;
      padding: 0;
      list-style: none;
      font-size: 0.85rem;
    }
    .answers li {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }
    .answers b {
      font-weight: 500;
    }
    .chips {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 16px;
    }
    .chips.recipients {
      margin-top: 8px;
    }
    .chip.tag {
      color: var(--secondary-text-color);
    }
    .media {
      display: flex;
      flex-direction: column;
      align-items: flex-start;
      gap: 6px;
      margin-top: 12px;
    }
    .preview,
    .player {
      display: block;
      position: relative;
      max-width: min(100%, 420px);
      box-sizing: border-box;
      padding: 0;
      overflow: hidden;
      ${surface}
      background: var(--secondary-background-color);
      font: inherit;
      cursor: zoom-in;
    }
    .preview img {
      display: block;
      max-width: 100%;
      max-height: 220px;
    }
    .preview.video,
    .player {
      width: min(100%, 392px);
      cursor: pointer;
    }
    .preview.video img,
    .preview.video video {
      width: 100%;
      aspect-ratio: 16 / 9;
      max-height: 220px;
      object-fit: contain;
    }
    .player {
      max-height: 320px;
      cursor: auto;
    }
    .play {
      position: absolute;
      top: 50%;
      left: 50%;
      display: grid;
      place-items: center;
      width: 52px;
      height: 52px;
      margin: -26px 0 0 -26px;
      border-radius: 50%;
      color: var(--text-primary-color);
      background: color-mix(in srgb, var(--primary-color) 85%, transparent);
    }
    .play .icon {
      width: 30px;
      height: 30px;
    }
    .caption {
      position: absolute;
      right: 0;
      bottom: 0;
      left: 0;
      padding: 4px 10px;
      overflow: hidden;
      font-size: 0.8rem;
      text-align: left;
      text-overflow: ellipsis;
      white-space: nowrap;
      color: var(--primary-text-color);
      background: color-mix(in srgb, var(--card-background-color) 75%, transparent);
    }
    .chip.media-link {
      border-radius: 6px;
      color: var(--primary-color);
    }
    .media-name {
      color: var(--secondary-text-color);
    }
    .chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 28px;
      box-sizing: border-box;
      padding: 2px 10px;
      border-radius: 14px;
      border: 1px solid var(--divider-color);
      background: none;
      color: var(--primary-text-color);
      font: inherit;
      font-size: 0.85rem;
      text-decoration: none;
      max-width: 100%;
      overflow-wrap: anywhere;
    }
    .chip .icon,
    .chip ha-icon {
      color: var(--secondary-text-color);
    }
    ha-icon {
      --mdc-icon-size: 18px;
      display: inline-flex;
      flex: none;
    }
    .chip.origin {
      background: color-mix(in srgb, var(--primary-color) 8%, transparent);
      border-color: transparent;
    }
    a.chip.link:hover,
    button.chip:hover {
      border-color: var(--primary-color);
    }
    a.chip.link .icon:last-child {
      width: 14px;
      height: 14px;
      color: var(--primary-color);
    }
    button.chip {
      cursor: pointer;
    }
    button.chip .icon:last-child {
      transition: transform 0.15s;
    }
    button.chip.open .icon:last-child {
      transform: rotate(180deg);
    }
    .count {
      min-width: 18px;
      padding: 0 5px;
      box-sizing: border-box;
      border-radius: 9px;
      font-size: 0.75rem;
      text-align: center;
      color: var(--text-primary-color);
      background: var(--primary-color);
    }
    .recipient {
      padding-left: 2px;
      border-color: transparent;
      background: var(--secondary-background-color);
    }
    .avatar {
      width: 24px;
      height: 24px;
      border-radius: 50%;
      object-fit: cover;
      flex: none;
    }
    .avatar.initials {
      display: grid;
      place-items: center;
      font-size: 0.7rem;
      font-weight: 600;
      color: var(--text-light-primary-color);
      background: var(--light-primary-color);
    }
    .avatar.device {
      display: grid;
      place-items: center;
      background: var(--card-background-color);
    }
    .avatar.device .icon {
      width: 15px;
      height: 15px;
    }
    .muted {
      color: var(--secondary-text-color);
      font-size: 0.85rem;
    }
    .chip.muted {
      color: var(--secondary-text-color);
    }
    section {
      margin-top: 12px;
      padding: 10px 12px;
      border-radius: 8px;
      background: var(--secondary-background-color);
    }
    h4 {
      margin: 0 0 6px;
      font-size: 0.78rem;
      font-weight: 500;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--secondary-text-color);
    }
    ul {
      margin: 0;
      padding: 0;
      list-style: none;
    }
    li {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 4px 10px;
      padding: 6px 0;
    }
    li + li {
      border-top: 1px solid var(--divider-color);
    }
    li .chips {
      margin: 0;
    }
    li .recipient {
      background: var(--card-background-color);
    }
    .call-channel {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 0.85rem;
      color: var(--secondary-text-color);
      overflow-wrap: anywhere;
    }
    dl {
      display: grid;
      grid-template-columns: max-content 1fr;
      gap: 4px 16px;
      margin: 0;
      font-size: 0.85rem;
    }
    dt {
      color: var(--secondary-text-color);
    }
    dd {
      margin: 0;
      overflow-wrap: anywhere;
      color: var(--primary-text-color);
    }
    code,
    pre {
      font-family: var(--ha-font-family-code);
      font-size: 0.8rem;
    }
    .details h4 {
      margin-top: 12px;
    }
    pre {
      margin: 0;
      padding: 8px 10px;
      border-radius: 6px;
      overflow-x: auto;
      color: var(--primary-text-color);
      background: var(--card-background-color);
    }
    .more {
      display: flex;
      align-items: center;
      gap: 2px;
      margin: 6px 0 0 auto;
      padding: 4px 6px;
      border: none;
      border-radius: 6px;
      background: none;
      color: var(--secondary-text-color);
      font: inherit;
      font-size: 0.8rem;
      cursor: pointer;
    }
    .more:hover {
      color: var(--primary-color);
    }
    .more .icon {
      transition: transform 0.15s;
    }
    .more.open .icon {
      transform: rotate(180deg);
    }
    button:focus-visible,
    a:focus-visible {
      outline: 2px solid var(--primary-color);
      outline-offset: 2px;
    }
    @media (max-width: 600px) {
      .card {
        gap: 10px;
        padding: 12px 12px 4px;
      }
      .status,
      .check {
        width: 30px;
        height: 30px;
      }
      .indent {
        padding-left: 8px;
      }
    }
  `;
}

if (!customElements.get("notification-journal-record")) {
  customElements.define("notification-journal-record", NotificationJournalRecord);
}
