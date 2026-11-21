import { css } from "lit";

/** The surface of a card, as `ha-card` draws it: only its optional variables get a fallback. */
export const surface = css`
  background: var(--card-background-color);
  border-radius: var(--ha-card-border-radius, 12px);
  border: var(--ha-card-border-width, 1px) solid var(--ha-card-border-color, var(--divider-color));
  box-shadow: var(--ha-card-box-shadow, none);
`;

/** Icons, icon buttons, segmented views, focus, busy and empty states the panel and the statistics share. */
export const controlStyles = css`
  .icon {
    width: 24px;
    height: 24px;
    fill: currentColor;
    flex: none;
  }
  .icon-button {
    display: grid;
    place-items: center;
    width: 44px;
    height: 44px;
    padding: 0;
    border: none;
    border-radius: 50%;
    background: none;
    color: inherit;
    cursor: pointer;
  }
  .icon-button:hover {
    background: color-mix(in srgb, currentColor 10%, transparent);
  }
  .icon-button.small {
    width: 32px;
    height: 32px;
    color: var(--secondary-text-color);
  }
  .icon-button.small .icon {
    width: 18px;
    height: 18px;
  }
  select:focus-visible,
  button:focus-visible {
    outline: 2px solid var(--primary-color);
    outline-offset: 2px;
  }
  .busy {
    opacity: 0.6;
    transition: opacity 0.2s 0.15s;
  }
  .view {
    display: inline-flex;
    height: 34px;
    padding: 2px;
    box-sizing: border-box;
    border-radius: 17px;
    border: 1px solid var(--divider-color);
    background: var(--card-background-color);
  }
  .view button {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 0 12px;
    border: none;
    border-radius: 15px;
    background: none;
    color: var(--secondary-text-color);
    font: inherit;
    font-size: 0.875rem;
    cursor: pointer;
  }
  .view button .icon {
    width: 18px;
    height: 18px;
  }
  .view button.selected {
    color: var(--text-primary-color);
    background: var(--primary-color);
  }
  .empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 64px 16px;
    text-align: center;
    color: var(--secondary-text-color);
  }
  .empty .icon {
    width: 56px;
    height: 56px;
    opacity: 0.5;
  }
  .empty h2 {
    margin: 16px 0 4px;
    font-size: 1.1rem;
    font-weight: 500;
    color: var(--primary-text-color);
  }
  .empty p {
    margin: 8px 0;
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
  .primary-button {
    padding: 8px 16px;
    border: none;
    border-radius: 18px;
    background: var(--primary-color);
    color: var(--text-primary-color);
    font: inherit;
    font-size: 0.875rem;
    font-weight: 500;
    cursor: pointer;
  }
  .primary-button[disabled] {
    opacity: 0.5;
    cursor: default;
  }
  .icon-button[disabled] {
    opacity: 0.35;
    cursor: default;
    background: none;
  }
`;
