// The titlebar's theme button: shows the theme to switch to, and logs each switch.
import { $ } from '../../shared/dom.js';
import { svg } from '../../shared/icons.js';
import { EV } from '../../shared/events.js';
import { subscribe, activity } from '../../shared/store.js';
import { themeNow, toggleTheme } from '../../shared/theme.js';

function renderThemeBtn() {
  const b = $('#btn-theme'), dark = themeNow() === 'dark';
  b.innerHTML = svg(dark ? 'sun' : 'moon');
  b.setAttribute('aria-pressed', String(dark));
  b.title = dark ? 'Switch to the light theme' : 'Switch to the dark theme';
}

export function mount() {
  $('#btn-theme').addEventListener('click', toggleTheme);
  renderThemeBtn();
  subscribe(EV.themeChange, ({ theme }) => { renderThemeBtn(); activity(`Theme: ${theme}`); });
}
