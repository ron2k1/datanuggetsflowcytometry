"""datanuggets-flow's default values, kept in one place: the flow's own, and the library
defaults its settings start from (SEED to CENTER_METHODS, TSNE_PERPLEXITY and TSNE_SEED), copied
because the library keeps them private. tests/flow/test_flow_library_pins.py checks each copy
against the library's public behaviour."""

SEED = 291102  # WCluster's Wkmeans and DN.Wkmeans default to it too
SEED_MAX = 2**31 - 1  # R's .Machine$integer.max, the largest seed set.seed and RDraws take
DN_NUM1 = 10_000
CENTER_METHODS = ("mean", "random", "original")


# the flow gate finder's tunable values, as cfc.py calls it: the n_row by n_col window its local
# maxima are found in, and the area each peak grows, the cells closer than t1 grid cells with more
# than t2 times the peak's density; t11 and t21 for the first peak, t12 and t22 for the others
FINDER_N_ROW = 11
FINDER_N_COL = 11
FINDER_T11 = 22
FINDER_T21 = 0.25
FINDER_T12 = 20
FINDER_T22 = 0.5


# datanuggets-flow's defaults: the scatter channels it gates on; reference, cfc.py's mirrored_area,
# as the area rule, where the library's lymphmacro_finder defaults to find_area; the channels it
# clusters, every -A channel but the scatter ones; the arcsinh cofactor; the Scale stage, each
# channel centred and scaled to SD 1 by its mean and SD pooled over the files; nuggets per file,
# where create_dn's own default is DN_NUM2; every core for create_dn, which doesn't change its
# results; the clusters; and the output folder, named by the UTC time a run starts
FLOW_FSC = "FSC-A"
FLOW_SSC = "SSC-A"
FLOW_DISC = "reference"
FLOW_CHANNEL_SUFFIX = "-A"
FLOW_SCATTER_PREFIXES = ("FSC", "SSC")
# the Transform stage's cofactor. "auto" picks one per clustered channel, once per run and before
# any arcsinh, from the raw values of the cells the run clusters (the populations kept, after the
# row filters, in the files it keeps): a channel with at least FLOW_COFACTOR_MIN_NEGATIVE of those
# cells below 0 takes the SD of its cloud below 0, the median of |x| over them divided by
# FLOW_COFACTOR_MAD_Z, as it is for a zero-centred Gaussian, but no less than FLOW_COFACTOR_FLOOR;
# any other channel takes FLOW_COFACTOR_FLOOR. arcsinh(x / c) splits a zero-centred Gaussian of SD
# s into two humps exactly when c < s, so a cofactor at least the SD of the cells below 0 keeps
# that cloud one population, and the floor keeps the rest of the channel logarithmic, where 6000
# for every channel left the long right tails linear. The median is read from a histogram of |x|
# in log-spaced bins, FLOW_COFACTOR_HIST's low and high edges at its bins per decade (about 0.58%
# wide), with one bin below and one above, so the files are pooled in bounded memory and in any
# order. On whole public files with no gate, FlowCAP's FACSAria-type files (0092, 0094, 0253 and
# 0255) have 6% to 21% of their cells below 0 on every marker channel, with an SD of 16 to 36, so
# every channel takes 150; on the Aurora demo files (190, 193, 199 and 223) six of the 32 do not:
# CD8 338, CD14 350, ACE2 210, CD19 204, CD123 198 and CCR4 175. The guard keeps a few stray
# negatives from setting a channel's cofactor: CCR7's spread there is 698 from 0.12% of the cells,
# and eFluor 450's comes from about ten events. FLOW_COFACTOR_WIDE is the one number a run used
# before the Transform stage was recorded, which a record without one is read back with.
FLOW_COFACTOR_AUTO = "auto"
FLOW_COFACTOR = FLOW_COFACTOR_AUTO
FLOW_COFACTOR_FLOOR = 150.0
FLOW_COFACTOR_MIN_NEGATIVE = 0.01
FLOW_COFACTOR_MAD_Z = 0.6745  # the median of |z| for a standard normal z
FLOW_COFACTOR_HIST = (1e-2, 1e8, 400)  # low and high edges of |x|, and bins per decade
FLOW_COFACTOR_WIDE = 6000.0
FLOW_TIME_PATTERN = r"^(time|hdr-t)\b"  # matched ignoring case: Time, Time (s), HDR-T
FLOW_STANDARDIZE = True
# the Scale stage warns when a channel's skewness after the Transform stage is beyond this either
# way: mean and SD then follow its tail, so most cells take a narrow band of the scaled axis
FLOW_SKEW_WARN = 5.0
FLOW_DN_NUM2 = 1000
FLOW_N_JOBS = -1
FLOW_K = 8
# the flow's clustering of the pooled nuggets: weighted k-means, WCluster 1.3.0's Wkmeans, R's
# implementation of Algorithm 3 of Beavers et al. (JCGS 34(1), 2025), or the hierarchical tree
# (Whclust, cut by cut_tree), still available. R starts each run from a random partition and adds
# 20 weighted Lloyd steps to each round, where the paper starts from K nugget centers and moves
# single nuggets. num_init is the paper's ten starts (Sec 4). max_iter is ours: R's default is 10,
# and the paper repeats its single-nugget step until no nugget moves, allowing a cap it gives no
# value for. The nugget centers default to "original", the stage-2 points that build the nuggets,
# which Cabrera's group prefers to the means (create.DN's own default is "mean").
FLOW_METHODS = ("wkmeans", "tree")
FLOW_METHOD = "wkmeans"
FLOW_CENTER_METHOD = "original"
FLOW_NUM_INIT = 10
FLOW_MAX_ITER = 100
# the random draws behind each file's create_dn: "r", R's set.seed(seed) draws (RDraws), so the
# nuggets are create.DN's; or "numpy", NumPy's Generator from the int seed, which every run
# recorded before draws existed used. Weighted k-means always draws R's, as every run of it has.
DRAWS = ("r", "numpy")
FLOW_DRAWS = "r"
# a run record or job written before method existed ran the tree on mean centers, and one written
# before draws existed drew its nuggets with NumPy
FLOW_LEGACY_METHOD = "tree"
FLOW_LEGACY_CENTER_METHOD = "mean"
FLOW_LEGACY_DRAWS = "numpy"
FLOW_OUT_DIR = "outputs"
FLOW_RUN_NAME = "flow-%Y%m%d-%H%M%S-%fZ"
FLOW_GATES_NAME = "flow-gates-%Y%m%d-%H%M%S-%fZ"
FLOW_SPILL_TOL = 1e-3  # how far from the identity a file's spillover matrix may be before a warning
FLOW_GATE_DPI = 110  # local_maxima.png and gates.png
FLOW_RESULT_DPI = 150  # the clustering's figures

# the t-SNE of the clustered nuggets: its perplexity, lowered to (n - 1) / 3 for n nuggets when
# that's smaller, as scikit-learn needs it below n, and its seed
TSNE_PERPLEXITY = 30.0
TSNE_SEED = 0
PCA_VIEW_COMPONENTS = 5  # the PCs cells.csv gives each sampled row, fewer with fewer variables

# datanuggets-flow's sample comparison: the cells per file sampled into cells.csv (0 writes
# none), the pseudocount of group_summary.csv's log2 fold change in cells of each kept file (half
# a cell: 100 * 0.5 / N_f percentage points for a file of N_f kept cells, averaged over the run's
# kept files), and the names a group may take
FLOW_CELLS_PER_FILE = 2000
FLOW_LOG2FC_CELLS = 0.5
FLOW_GROUP_NAME = r"^[A-Za-z0-9][A-Za-z0-9 _.+-]{0,39}$"
FLOW_LEGEND_ROWS = 25  # clusters_tsne.png legend rows per column, so k = 100 fits beside the plot

# the live-cells step's display defaults (datanuggets_flow.livecells), none of them a threshold:
# bins per histogram, the pooled quantiles a channel's range spans, the margin added to each side
# of it (a share of its width, cut back to the data's own extremes), the width a range of one
# value is opened to, and the schema of the kept values' saved file
LIVECELLS_BINS = 128
LIVECELLS_RANGE_QUANTILES = (0.001, 0.999)
LIVECELLS_RANGE_PAD = 0.05
LIVECELLS_FLAT_WIDTH = 1.0
LIVECELLS_SCHEMA = "datanuggets-livecells/1"
