// The package's channel rules on $PnN names as stored, by its constants (config.js): the time
// channel, the default clustering channels (its default_channels) and the two channels a gate
// takes when none are set (its gate_channels). No name is required: a file without forward or
// side scatter, as from a mass cytometer, gets marker channels instead. No DOM, so app/tests runs
// it in Node and checks it against the package.
import { FLOW_CHANNEL_SUFFIX, FLOW_SCATTER_RES, FLOW_TIME_RE } from './config.js';

export const isTime = name => FLOW_TIME_RE.test(name);

// The channels clustered when none are named, in names' order: every -A channel but forward and
// side scatter, or every channel but those and Time when fewer than two -A ones differ.
export function defaultChannels(names) {
  const markers = names.filter(n => !FLOW_SCATTER_RES.some(re => re.test(n)));
  const areas = markers.filter(n => n.endsWith(FLOW_CHANNEL_SUFFIX));
  return new Set(areas).size < 2 ? markers.filter(n => !isTime(n)) : areas;
}

// [fsc, ssc], the gate's channels across and up for a file with channels names, each kept when
// given. One not given is the file's first forward (or side) scatter ending in -A, else its first
// named so, else the first of its default channels; never the other's channel; null when the file
// has none left.
export function gateChannels(names, fsc = null, ssc = null) {
  const [forward, side] = FLOW_SCATTER_RES;
  const pick = (scatter, other) => {
    const named = names.filter(n => scatter.test(n) && n !== other);
    const rest = defaultChannels(names).filter(n => n !== other);
    return [...named.filter(n => n.endsWith(FLOW_CHANNEL_SUFFIX)), ...named, ...rest][0] ?? null;
  };
  const across = fsc || pick(forward, ssc);
  return [across, ssc || pick(side, across)];
}
