import { css, html, LitElement, nothing, type TemplateResult } from "lit";
import { ref } from "lit/directives/ref.js";

import { icon, mdiClose } from "./icons";
import { countText, type Localize } from "./localize";
import { spokenText } from "./media";
import { controlStyles } from "./styles";
import type { HassConnection, NotificationRecord } from "./types";
import { errorMessage, showWhenReady } from "./util";

/** What a notification can be sent to, as `notification_journal/targets` lists it. */
export interface Targets {
  notify_entity: Named[];
  notify_action: { service: string; name: string; companion: boolean }[];
  engines: Named[];
  speak: Named[];
  announce: Named[];
  /** Whether the Companion app's actions get the notification's image, buttons and tag too. */
  same_medium: boolean;
}

interface Named {
  entity_id: string;
  name: string;
}

type Target =
  | { kind: "notify_entity"; entity_id: string }
  | { kind: "notify_action"; service: string }
  | { kind: "speak"; engine: string; entity_id: string }
  | { kind: "announce"; entity_id: string };

/** A dialog that sends a notification again to targets an administrator picks, after asking once more. */
export class NotificationJournalSend extends LitElement {
  static override properties = {
    record: { attribute: false },
    connection: { attribute: false },
    localize: { attribute: false },
    _targets: { state: true },
    _chosen: { state: true },
    _engine: { state: true },
    _step: { state: true },
    _error: { state: true },
  };

  declare record: NotificationRecord;
  declare connection: HassConnection;
  declare localize: Localize;
  declare _targets: Targets | undefined;
  /** The chosen targets by key, with their names. */
  declare _chosen: Map<string, string>;
  declare _engine: string;
  declare _step: "choose" | "confirm" | "sending";
  declare _error: string | undefined;

  constructor() {
    super();
    this._chosen = new Map();
    this._engine = "";
    this._step = "choose";
  }

  override connectedCallback(): void {
    super.connectedCallback();
    void this._load();
  }

  private async _load(): Promise<void> {
    try {
      const targets = await this.connection.sendMessagePromise<Targets>({
        type: "notification_journal/targets",
        record_id: this.record.id,
      });
      this._targets = targets;
      this._engine = targets.engines[0]?.entity_id ?? "";
    } catch (error) {
      this._error = this.localize("send_failed", { message: errorMessage(error) });
    }
  }

  private _target(key: string): Target {
    const [kind, id] = key.split(" ", 2) as [Target["kind"], string];
    if (kind === "notify_action") return { kind, service: id };
    if (kind === "speak") return { kind, engine: this._engine, entity_id: id };
    return { kind, entity_id: id };
  }

  override render(): TemplateResult {
    const localize = this.localize;
    return html`<dialog ${ref(this._open)} @close=${this._closed} @cancel=${this._cancel}>
      <header>
        <h2>${localize("send_to_title")}</h2>
        <button class="icon-button" title=${localize("close")} @click=${this._close}>
          ${icon(mdiClose, localize("close"))}
        </button>
      </header>
      <blockquote>
        ${this.record.title ? html`<b>${this.record.title}</b><br />` : nothing}${spokenText(this.record) ?? this.record.message}
      </blockquote>
      ${this._step === "choose" ? this._choose(localize) : this._confirm(localize)}
      ${this._error ? html`<p class="error" role="alert">${this._error}</p>` : nothing}
    </dialog>`;
  }

  private _choose(localize: Localize): TemplateResult {
    const targets = this._targets;
    if (!targets) return html`<p class="hint">${localize("loading")}</p>`;
    const companion = targets.notify_action.filter((action) => action.companion);
    const others = targets.notify_action.filter((action) => !action.companion);
    const byAction = (actions: typeof companion) =>
      actions.map((action) => ({ key: `notify_action ${action.service}`, name: action.name }));
    const byEntity = (kind: string, entities: Named[]) =>
      entities.map((entity) => ({ key: `${kind} ${entity.entity_id}`, name: entity.name }));
    const speakers = targets.engines.length ? targets.speak : [];
    return html`
      <div class="sections">
        ${this._section(
          localize("send_companion"),
          localize(targets.same_medium ? "send_receives_all" : "send_receives_titled"),
          byAction(companion),
        )}
        ${this._section(localize("send_notify"), localize("send_receives_titled"), [
          ...byEntity("notify_entity", targets.notify_entity),
          ...byAction(others),
        ])}
        ${this._section(
          localize("send_speak"),
          localize("send_receives_spoken"),
          byEntity("speak", speakers),
          targets.engines.length > 1
            ? html`<label class="engine"
                >${localize("send_engine")}
                <select @change=${(event: Event) => (this._engine = (event.target as HTMLSelectElement).value)}>
                  ${targets.engines.map(
                    (engine) =>
                      html`<option value=${engine.entity_id} ?selected=${engine.entity_id === this._engine}>
                        ${engine.name}
                      </option>`,
                  )}
                </select></label
              >`
            : nothing,
        )}
        ${this._section(localize("send_announce"), localize("send_receives_spoken"), byEntity("announce", targets.announce))}
      </div>
      <footer>
        <button class="text-button" @click=${this._close}>${localize("cancel")}</button>
        <button class="primary-button" ?disabled=${!this._chosen.size} @click=${() => (this._step = "confirm")}>
          ${localize("send_next")}
        </button>
      </footer>
    `;
  }

  private _section(
    title: string,
    receives: string,
    options: { key: string; name: string }[],
    extra: TemplateResult | typeof nothing = nothing,
  ): TemplateResult | typeof nothing {
    if (!options.length) return nothing;
    return html`<fieldset>
      <legend>${title}</legend>
      <p class="hint">${receives}</p>
      ${extra}
      ${options.map(
        (option) =>
          html`<label class="option">
            <input
              type="checkbox"
              .checked=${this._chosen.has(option.key)}
              @change=${(event: Event) =>
                this._toggle(option.key, option.name, (event.target as HTMLInputElement).checked)}
            />
            ${option.name}
          </label>`,
      )}
    </fieldset>`;
  }

  private _confirm(localize: Localize): TemplateResult {
    const sending = this._step === "sending";
    return html`
      <p>${countText(localize, this._chosen.size, "send_confirm_one", "send_confirm")}</p>
      <ul class="chosen">
        ${[...this._chosen.values()].map((name) => html`<li>${name}</li>`)}
      </ul>
      <footer>
        <button class="text-button" ?disabled=${sending} @click=${() => (this._step = "choose")}>
          ${localize("back")}
        </button>
        <button class="primary-button" ?disabled=${sending} @click=${this._send}>
          ${localize(sending ? "resending" : "send")}
        </button>
      </footer>
    `;
  }

  private _toggle(key: string, name: string, on: boolean): void {
    const chosen = new Map(this._chosen);
    if (on) chosen.set(key, name);
    else chosen.delete(key);
    this._chosen = chosen;
  }

  private readonly _send = async (): Promise<void> => {
    this._step = "sending";
    this._error = undefined;
    const chosen = [...this._chosen];
    try {
      const { errors } = await this.connection.sendMessagePromise<{ errors: (string | null)[] }>({
        type: "notification_journal/send",
        record_id: this.record.id,
        targets: chosen.map(([key]) => this._target(key)),
      });
      const failed = chosen.flatMap((entry, index) => (errors[index] ? [{ entry, error: errors[index] }] : []));
      if (!failed.length) {
        this._finish(countText(this.localize, chosen.length, "sent_to_one", "sent_to"));
        return;
      }
      this._chosen = new Map(failed.map(({ entry }) => entry));
      const message = failed.map(({ entry: [, name], error }) => `${name}: ${error}`);
      this._error = this.localize("send_failed", { message: message.join("; ") });
      this._step = "confirm";
    } catch (error) {
      this._error = this.localize("send_failed", { message: errorMessage(error) });
      this._step = "confirm";
    }
  };

  private _dialog: HTMLDialogElement | undefined;

  private readonly _open = (element: Element | undefined): void => {
    if (element instanceof HTMLDialogElement) {
      this._dialog = element;
      showWhenReady(this, element);
    }
  };

  private readonly _cancel = (event: Event): void => {
    if (this._step === "sending") event.preventDefault();
  };

  private readonly _close = (): void => {
    if (this._step !== "sending") this._finish(undefined);
  };

  /** A dialog closed while sending opens again, so its result is not lost. */
  private readonly _closed = (): void => {
    if (this._step === "sending" && this._dialog) showWhenReady(this, this._dialog);
    else this._finish(undefined);
  };

  private _finish(notice: string | undefined): void {
    this.dispatchEvent(new CustomEvent("send-done", { detail: { notice }, bubbles: true, composed: true }));
  }

  static override styles = [
    controlStyles,
    css`
      dialog {
        width: min(520px, calc(100vw - 32px));
        max-height: calc(100vh - 64px);
        box-sizing: border-box;
        padding: 16px 20px;
        border: none;
        border-radius: var(--ha-dialog-border-radius, 24px);
        background: var(--card-background-color);
        color: var(--primary-text-color);
        font-family: var(--ha-font-family-body);
      }
      dialog::backdrop {
        backdrop-filter: var(--ha-dialog-scrim-backdrop-filter, var(--dialog-backdrop-filter, none));
        background-color: var(--mdc-dialog-scrim-color, none);
      }
      header {
        display: flex;
        align-items: center;
        justify-content: space-between;
      }
      h2 {
        margin: 0;
        font-size: 1.25rem;
        font-weight: 400;
      }
      blockquote {
        margin: 12px 0;
        padding: 8px 12px;
        border-left: 3px solid var(--divider-color);
        color: var(--secondary-text-color);
        font-size: 0.875rem;
        overflow-wrap: anywhere;
      }
      .sections {
        display: grid;
        gap: 12px;
      }
      fieldset {
        margin: 0;
        padding: 8px 12px 10px;
        border: 1px solid var(--divider-color);
        border-radius: 12px;
      }
      legend {
        padding: 0 4px;
        font-weight: 500;
      }
      .hint {
        margin: 0 0 6px;
        color: var(--secondary-text-color);
        font-size: 0.8rem;
      }
      .option,
      .engine {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 4px 0;
        font-size: 0.875rem;
      }
      .option input {
        accent-color: var(--primary-color);
      }
      footer {
        display: flex;
        justify-content: flex-end;
        gap: 8px;
        margin-top: 16px;
      }
      .chosen {
        margin: 0;
        padding-left: 20px;
        font-size: 0.875rem;
      }
      .error {
        margin: 12px 0 0;
        color: var(--error-color);
        font-size: 0.875rem;
      }
    `,
  ];
}

if (!customElements.get("notification-journal-send")) {
  customElements.define("notification-journal-send", NotificationJournalSend);
}
