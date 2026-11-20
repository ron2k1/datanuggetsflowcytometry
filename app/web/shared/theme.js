// Light is the initial theme whatever the OS prefers; the toggle switches to dark and back, and
// the choice persists in localStorage["dn-theme"]. shared/theme-boot.js applies a stored dark choice
// before the first paint. A switch emits EV.themeChange.
import { DEFAULT_THEME, STORAGE, THEMES } from './config.js';
import { EV } from './events.js';
import { emit } from './store.js';

export const themeNow = () => (document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light');

export function setTheme(t) {
  if (!THEMES.includes(t)) t = DEFAULT_THEME;
  if (t === 'dark') document.documentElement.setAttribute('data-theme', 'dark');
  else document.documentElement.removeAttribute('data-theme');
  try { localStorage.setItem(STORAGE.theme, t); } catch (e) { /* storage unavailable: the choice lasts this visit */ }
  emit(EV.themeChange, { theme: t });
}

export const toggleTheme = () => setTheme(themeNow() === 'dark' ? 'light' : 'dark');
