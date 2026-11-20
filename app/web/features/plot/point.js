// The point card's numbers (docs/app/cluster-panel.md "A point's numbers"): one nugget or sampled
// cell of the plot model, with each marker's value as plotted, in the run's Transform stage units,
// and back in the file's units. The run clusters arcsinh(x / c) of the values flowio reads from
// the .fcs file (uncompensated), c per channel or one number, so x = c sinh(v): for a cell that is
// the value the run read; for a nugget, its center on the file's scale. No DOM here, so app/tests
// runs it in Node.
import { plotTransform, perChannel, cofactorFor } from '../../shared/cofactor.js';
import { PAYLOAD_SIG_DIGITS } from '../../shared/config.js';
import { fmtNum } from '../../shared/format.js';

// Channel j's plotted value v in the file's units under transform t; v itself without an arcsinh.
export const fromPlotted = (t, j, v) => (t.name === 'arcsinh' ? cofactorFor(t, j) * Math.sinh(v) : v);

// How finely v pins down its value in the file. The payload rounds v to PAYLOAD_SIG_DIGITS
// significant digits, so v is known to half a unit u in its last digit, and c sinh(v) to about
// c cosh(v) u / 2, which grows with v: at 5.715 and c = 310.29 it is 24. The power of ten at or
// above that is the step the card shows the file value to. null when that value is as exact as
// v: no arcsinh, or v is 0.
export function fileStep(t, j, v) {
  if (t.name !== 'arcsinh' || !v || !Number.isFinite(v)) return null;
  const e = +v.toExponential().split('e')[1];
  const h = (cofactorFor(t, j) * Math.cosh(v) * 10 ** (e - PAYLOAD_SIG_DIGITS + 1)) / 2;
  return h > 0 ? 10 ** Math.ceil(Math.log10(h)) : null;
}

// Value x rounded to step (fileStep): with thousands separators for the card, plain for a
// spreadsheet. As fmtNum, or as JavaScript writes x, without a step. A value that rounds to 0
// shows no minus sign.
export function fmtFile(x, step, plain = false) {
  if (step == null) return plain ? String(x) : fmtNum(x);
  const d = Math.max(0, -Math.round(Math.log10(step))), y = Math.round(x / step) * step + 0;
  return plain ? y.toFixed(d) : y.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
}

const AXES = ['x', 'y', 'z'];

/**
 * Row i of model M (makeModel) for the card.
 * @param {object} P  the plot payload
 * @param {object} M  the plot model
 * @param {number} i  the model's row
 * @param {string[]} [drawn]  the drawn axes' keys ('v3', 'p0', 't1'): a marker on an axis says which
 * @returns {{src: string, cluster: number, file: object|null, nugget: number, event: number|null,
 *   weight: number|null, transform: string, perChannel: boolean,
 *   rows: {j: number, name: string, short: string, plotted: number, file: number,
 *          step: number|null, cofactor: number|null, axis: string|null}[]}}
 *   nugget is the nugget's number within its file from 1, a cell's own nugget for a cell; event
 *   is a cell's event in its file from 1, null for a nugget. file is c sinh(plotted) unrounded;
 *   step is the place to show it to (fileStep).
 */
export function pointNumbers(P, M, i, drawn = []) {
  const t = plotTransform(P), arc = t.name === 'arcsinh', cells = M.src === 'cells';
  const axis = new Map(drawn.map((k, a) => [k, AXES[a]]));
  const file = (P.files || []).find(f => f.number === M.file[i]) || null;
  return {
    src: M.src,
    cluster: M.cluster[i],
    file,
    nugget: M.nugget[i] + 1,
    event: cells ? M.index[i] + 1 : null,
    weight: cells ? null : M.weight[i],
    transform: arc ? 'arcsinh' : 'none',
    perChannel: arc && perChannel(t),
    rows: P.columns.map((name, j) => {
      const v = M.column('v' + j)[i];
      return { j, name, short: P.short_columns[j], plotted: v, file: fromPlotted(t, j, v), step: fileStep(t, j, v), cofactor: arc ? cofactorFor(t, j) : null, axis: axis.get('v' + j) || null };
    }),
  };
}
