// The tab-view registry and named slots: the two places a feature plugs UI into another feature's
// screen without importing it. A feature registers a view for its tab kind (the shell draws
// whichever view the active tab names), or a part for a named slot (the screen that owns the slot
// draws every part registered for it).

/**
 * What the shell hands a view while it is on screen.
 * @typedef {object} EditorHost
 * @property {(keys: { back: () => void, cancelBox: () => boolean } | null) => void} setKeys
 *   Backspace / Alt+Left call back(); Esc calls cancelBox().
 * @property {(text: (() => string) | null) => void} setStatus  A status-bar text for this tab, redrawn now.
 * @property {() => void} refreshStatus  Redraw the status bar.
 * @property {() => void} refreshPanel  Redraw the terminal panel.
 */

/**
 * A tab kind's view. Tab keys look like `kind:id[~n]`.
 * @typedef {object} View
 * @property {(key: string) => { name: string, hint?: string|null, icon: string, cls?: string }} title
 * @property {(key: string) => string[]} [crumbs]
 * @property {(body: HTMLElement, key: string, host: EditorHost) => ((() => void) | void)} render
 *   Draws into body and may return a cleanup the shell calls before the next render.
 * @property {(key: string) => ({ path: string, lines: object[] } | null)} [output]  The terminal's Output tab.
 */

const views = new Map();
/** @param {string} kind @param {View} view */
export const registerView = (kind, view) => { views.set(kind, view); };
/** @returns {View|null} */
export const viewFor = kind => views.get(kind) || null;

const slots = new Map();
// Adds a part to slot `name`; the slot's owner documents what a part must provide.
export function registerSlot(name, part) {
  if (!slots.has(name)) slots.set(name, []);
  slots.get(name).push(part);
}
export const slotParts = name => slots.get(name) || [];
