// Plotly styling that follows the theme. The colours of a figure's chrome (fonts, grid and axis
// lines, hover labels, 3D panes, the sequential and diverging scales, the greys of other clusters'
// points and lines) are the --plot-* tokens in styles/tokens.css, read here when a figure is
// built; a view that draws Plotly redraws on EV.themeChange. Cluster colours are not here: they
// are the payload's (contract 7).
import { FILE_COLORS, GROUP_COLORS } from './config.js';
import { themeNow } from './theme.js';

export const PLOT_FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';
export const PLOT_MONO = 'ui-monospace, "Cascadia Code", Menlo, Consolas, monospace';

const TOKENS = {
  fg: '--plot-fg', fg2: '--plot-fg-2', fg3: '--plot-fg-3', line: '--plot-line', grid: '--plot-grid',
  hover: '--plot-hover', paneX: '--plot-pane-x', paneY: '--plot-pane-y', paneZ: '--plot-pane-z',
  ink: '--plot-ink', ref: '--plot-ref', accent: '--accent', dim: '--plot-dim', ghost: '--plot-ghost',
};
const STOPS = [0, 1, 2, 3, 4];
let memo = null;

/**
 * The current theme's plot colours, read from the tokens once per theme.
 * @returns {{fg: string, fg2: string, fg3: string, line: string, grid: string, hover: string,
 *   paneX: string, paneY: string, paneZ: string, ink: string, ref: string, accent: string,
 *   dim: string, ghost: string, seq: [number, string][], div: [number, string][]}}
 */
export function plotTheme() {
  const theme = themeNow();
  if (memo && memo.theme === theme) return memo.T;
  const css = getComputedStyle(document.documentElement);
  const read = name => css.getPropertyValue(name).trim();
  const T = Object.fromEntries(Object.entries(TOKENS).map(([k, name]) => [k, read(name)]));
  T.seq = STOPS.map(i => [i / 4, read(`--plot-seq-${i}`)]);
  T.div = STOPS.map(i => [i / 4, read(`--plot-div-${i}`)]);
  memo = { theme, T };
  return T;
}

// Transparent backgrounds, so the container's --plot-bg shows, with the theme's fonts and hovers.
export const baseLayout = T => ({
  paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
  font: { family: PLOT_FONT, color: T.fg2, size: 11 },
  hoverlabel: { bgcolor: T.hover, bordercolor: T.line, font: { family: PLOT_MONO, size: 11, color: T.fg } },
});

// File n's colour (1-based): the Okabe-Ito set, whose black is the theme's ink so it shows on dark.
export const fileColor = (T, n) => {
  const c = FILE_COLORS[(n - 1) % FILE_COLORS.length];
  return c === '#000000' ? T.ink : c;
};
// Group bar gi on Compare: the reference group's neutral follows the theme, the others are fixed.
export const groupColor = (T, gi) => (gi % GROUP_COLORS.length === 0 ? T.ref : GROUP_COLORS[gi % GROUP_COLORS.length]);
