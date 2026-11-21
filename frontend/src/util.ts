/** A value kept in the browser for the next visit; null without one or without storage. */
export function stored(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

/** Keep a value in the browser; without storage it lasts until the page reloads. */
export function store(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Without storage the choice lasts until the page reloads.
  }
}

/** The message of an error from the WebSocket connection or elsewhere. */
/** Opens a dialog modally once its element has rendered, if it is still on the page and closed. */
export function showWhenReady(host: { updateComplete: Promise<unknown> }, dialog: HTMLDialogElement): void {
  void host.updateComplete.then(() => {
    if (dialog.isConnected && !dialog.open) dialog.showModal();
  });
}

export function errorMessage(error: unknown): string {
  if (typeof error === "object" && error && "message" in error) return String(error.message);
  return String(error);
}
