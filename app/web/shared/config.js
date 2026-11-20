// Every UI constant in one place. Caps and analysis defaults are not here: they come from
// GET /config at run time, so the page never disagrees with the server.

export const API_BASE = '/api/v1';
export const FIXTURE_DIR = 'fixtures';
export const STORAGE = { theme: 'dn-theme', fixtures: 'dn-fixtures', terminal: 'dn-terminal' };
export const THEMES = ['light', 'dark'];
export const DEFAULT_THEME = 'light';

export const POLL_MS = 1000;            // job polling while queued or running
export const TOAST_MS = 3600;
export const DRAWER_MAX_PX = 760;       // explorer becomes a drawer at or below this width
export const K_MIN = 2;
export const K_FALLBACK_MAX = 100;      // only when /config has no limits.k_max

export const PLOTLY_VERSION = '3.0.1';
// The significant digits the server rounds a payload's floats to, its SIG_DIGITS (core/config.py;
// app/tests pins them): the point card shows a value derived from one no finer than they fix.
export const PAYLOAD_SIG_DIGITS = 4;
export const HISTORY = { gapMs: 400, cap: 50 };
export const SETTLE_MS = 120;           // 3D camera read-back after a drag stops
export const EYE = { minDeg: 8, maxDeg: 75, minR: 1.25, maxR: 5 };
export const DEFAULT_CAMERA = { eye: { x: 1.5, y: 1.4, z: 0.95 }, center: { x: 0, y: 0, z: -0.08 }, up: { x: 0, y: 0, z: 1 } };
export const TWEEN_MS = 450;            // animated axis change
export const CLICK_SLOP = 4;            // px a 3D press may move and still click a point (not rotate)
export const HOVER_DEBOUNCE_MS = 40;    // legend hover highlight
export const LIVECELLS_BINS = 128;      // histogram bins the Live cells step asks for (contract-livecells 2.4)
export const COUNTS_QUIET_MS = 300;     // Live cells: quiet after a line moves before POST .../counts
export const PICK_QUIET_MS = 400;       // Live cells: quiet after a channel pick before POST .../livecells
// Live cells: channels its dropdowns never offer. Forward and side scatter are set in the gate
// settings; the prefixes are the package's FLOW_SCATTER_PREFIXES (app/tests pins them). The
// upload view shows header ranges only for the other channels (shared/cofactor.js isMarkerChannel).
export const LIVECELLS_SCATTER_PREFIXES = ['FSC', 'SSC'];
// A dataset's colour channels: the names that end in this and do not start with a scatter prefix
// above, the package's default clustering rule (its FLOW_CHANNEL_SUFFIX; app/tests pins it).
export const FLOW_CHANNEL_SUFFIX = '-A';
// POST /datasets's limits, the server's DATASET_* (core/config.py), which the fixture transport
// checks as the server does; a length counts code points.
export const DATASET_NAME_MAX = 60;     // characters in a dataset's name
export const DATASET_CHANNELS_MAX = 512; // channels in one request
export const DATASET_CHANNEL_CHARS = 100; // characters in one channel name
export const DATASET_CHANNELS_BYTES = 16000; // one channel list, as Python's json.dumps writes it
export const DATASETS_MAX = 100;        // names one workspace keeps; at the cap, those of sets no upload has go
// The time channel: Time, Time (s), and HDR-T as some cytometers name it; the package's
// FLOW_TIME_PATTERN, matched ignoring case (app/tests pins it).
export const LIVECELLS_TIME_RE = /^(time|hdr-t)\b/i;
// Gate settings: the Forward and Side scatter dropdowns offer only the channels whose names start
// with these (FSC-A, FSC-H, ...), or every channel when a file has none.
export const GATE_SCATTER = { fsc: 'FSC', ssc: 'SSC' };
export const CLICK_SLOP_PX = 5;         // a press that moves further is a drag, not a click

// Marker look: solid, opaque, no outline. Sizes in px. The nugget sizes are for a run of up to
// refNuggets nuggets: about 2,000 nuggets then draw their clusters as filled areas rather than as
// dots with gaps between them. A run of n nuggets past that draws them sqrt(refNuggets / n) as
// large, weight sizes too, so the dots cover about the same area instead of piling up; the factor
// stops where the default size reaches floor2d in 2D or floor3d in 3D (Pairs keeps floor2d's ratio
// to size2d). n is the whole run's count, so hiding or picking clusters never resizes a point.
// Cells keep their sizes. By weight, a nugget's diameter is weightMin + weightSpan x
// ln(1 + w) / ln(1 + wmax) before that factor (docs/app/cluster-panel.md).
export const MARKER = {
  size2d: 12, size3d: 7, cells2d: 4, cells3d: 2.6, pairs: 7,
  weightMin2d: 3, weightSpan2d: 21, weightMin3d: 2, weightSpan3d: 12,
  refNuggets: 2000, floor2d: 4, floor3d: 2.5,
};
// Zooming a 2D or 3D nuggets view in from Fit grows its nuggets: by the view's zoom to this power,
// held between 1 and max. 0.5 grows a dot's area with the zoom while the gaps between dots grow
// with its square, so zooming in still pulls them apart. 2D's zoom is the smaller of its two axes'
// (Fit's span over the view's); 3D's is its box's (the smallest of three) times its camera's.
export const ZOOM_GROW = { power: 0.5, max: 4 };
// The 3D wheel narrows the three axes about the hovered point (features/plot/zoom3.js), as the 2D
// wheel narrows two: Plotly's own 3D wheel moves the camera, which EYE.minR stops about 1.8 times
// closer than Fit. Each wheel event scales the spans by exp(deltaY / wheelScale), deltaY held to
// +-wheelMax, Plotly's 2D wheel rule; maxZoom is the narrowest box, as Fit's spans over its.
export const ZOOM_3D = { wheelMax: 20, wheelScale: 200, maxZoom: 1e4 };
// The cluster panel draws a box from at least this many sampled cells (docs/app/cluster-panel.md).
export const BOX_MIN_CELLS = 5;
// Invisible points along each of the panel's boxes, whisker to whisker, that carry its hover label.
export const BOX_HOVER_POINTS = 24;
// The inspector's Point size: a factor on every size above, nuggets and cells alike, applied after
// a large run's shrink.
export const POINT_SCALE = { min: 0.5, max: 3, step: 0.1, start: 1 };
// Clusters outside the focus (the picked ones, or the hovered one) draw in the theme's
// --plot-dim grey by default, nuggets at scale x the size (cells are already the smallest marker
// and keep it). In 3D they sit in WebGL's transparent pass, which blends them over any picked
// point behind them, so they stay small and the dark theme's grey stays mid-tone: a pale one
// piled up to near-white over the picked clusters.
export const DIM = { scale: 0.6, grey: { 2: 0.22, 3: 0.16 }, own: { 2: 0.14, 3: 0.1 } };
export const OTHERS = [['grey', 'Grey'], ['own', 'Own colour'], ['hide', 'Hidden']];

// Colour by file: a fixed colour-blind-safe set (Okabe-Ito). With more files than colours the
// option is off, so nothing ever cycles. Read it through plot-base.js fileColor(), which draws
// the black in the theme's ink.
export const FILE_COLORS = ['#e69f00', '#56b4e9', '#009e73', '#cc79a7', '#f0e442', '#0072b2', '#d55e00', '#000000'];
// Group bars on Compare: the reference group is a neutral (plot-base.js groupColor() takes it from
// the theme), the others cycle after it.
export const GROUP_COLORS = ['#4a5060', '#d4500f', '#0072b2', '#009e73', '#cc79a7', '#e69f00'];

// The flow run's Transform stage; 'none' is sent as cofactor 0, arcsinh as 'auto' or a number.
export const FLOW_TRANSFORMS = [['arcsinh', 'Inverse hyperbolic sine, arcsinh(x / cofactor)'], ['none', 'None (linear)']];
// The flow run's Cluster stage: the package's FLOW_METHODS, its default (FLOW_METHOD) first, and
// two of create_dn's CENTER_METHODS, its default (FLOW_CENTER_METHOD) first (app/tests pins
// them). Settings written before the app sent the two name neither, and the package reads such
// a run as the hierarchical tree on mean centers (ClusterSettings.from_dict, its FLOW_LEGACY_*):
// so does shared/clustering.js clusteringOf.
export const FLOW_METHODS = [['wkmeans', 'Weighted k-means'], ['tree', 'Hierarchical tree']];
export const CENTER_METHODS = [['original', 'Original points'], ['mean', 'Means']];
export const FLOW_LEGACY = { method: 'tree', center_method: 'mean' };
export const FILTER_OPS = ['<', '<=', '>', '>=', '==', '!=', 'between', 'in'];
export const GROUP_RE = /^[A-Za-z0-9][A-Za-z0-9 _.+-]{0,39}$/;
export const DISC = [['reference', 'Reference (same gates as the original code)'], ['peak', 'Peak-centred (circle on each peak)']];
