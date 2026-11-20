# A point's numbers, cluster box plots and nugget weight sizes

What the app shows about one point and one cluster, and how nugget weights set marker sizes. The
point card and the box plots read only the plot and cells payloads (contract section 3.5) and the
run's manifest; the server is unchanged.

## A point's numbers

Click a point in the plot (2D, 3D or Pairs) and the point card opens beside it, with an open ring
over the point in 2D and 3D. The points of other clusters in grey are not clickable: their hovers
are off in 2D and 3D, and Pairs skips them. In 3D the card takes the point whose hover label
shows, on a release that moved less than `CLICK_SLOP` px (4): Plotly's 3D scene reports a click
only within 5 px of a point's center, and while the button is still down, so a drag that starts on
a point turns the view and leaves the card as it was. The 3D ring carries its point's hover label,
and a hover or click on it is one on its point: Plotly's 3D scene hovers whatever it drew nearest
the pointer, ring included, so a ring without a hover of its own left its point and the points
close around it with no hover and no click.

The card names the point and where it came from:

- A nugget: its number within its file (nuggets are numbered per file, from 1), its cluster, its
  file and group, and its cells (the nugget's weight).
- A sampled cell (the Cells view): its event, the row of its file from 1, its cluster, its file
  and group, and the nugget that holds it, by that nugget's number within the same file.

Then one row per marker, in the run's channel order:

| Column | What it is |
| --- | --- |
| Plotted | the value the plot draws, in the run's Transform stage units: `arcsinh(x / c)` |
| In the file | `c x sinh(plotted)`, the value back on the scale of the .fcs file's values |
| c | the channel's cofactor, shown when the run picked one per channel (auto) |

The run clusters `arcsinh(x / c)` of the events as flowio reads them from the file, uncompensated,
and the payload undoes the Scale stage, so for a cell **In the file** is the value the run read
for that event. For a nugget it is the nugget's center put back on that scale; the nugget's cells
spread around it.

**Plotted** has four significant digits, as the payload carries it, so it is known only to half a
unit in its last digit, and `c x sinh(plotted)` only to about `c x cosh(plotted)` times that, which
grows with the value: at a plotted 5.715 and a cofactor of 310.29, about 24. **In the file** is
rounded to the power of ten at or above that, here the hundreds, 47,100, on the card and in Copy;
a value of 0.1234 at c = 150 keeps the hundredths, 18.56. Copy gives the cofactor exact: it is the
run's own setting. A run with a cofactor of 0 clustered the values as stored: the card then has
one **Value** column. The markers
on the drawn axes are tagged x, y and z, so the ring's place on the axes reads off the Plotted
column.

**Copy** puts the table on the clipboard as tab-separated text, with each channel's full name and
cofactor. **Box plots of cluster N** opens the cluster's box plots. The card stays while the view,
the axes or the zoom change, and shuts with its close button, Esc, or a switch between Nuggets and
Cells (a row of one is not a row of the other). It sits between the plot and the inspector on a
window wider than 1,400 px; at 1,400 px or narrower it covers the inspector, and in the one-column
phone layout it follows the plot.

## Opening the box plots

A run's box plots are a tab of their own, **Box plots** and the run's id, beside its plot and
Compare tabs.

- **Box plots of cluster N** in the point card opens the tab on the point's cluster.
- The bar under the plot holds a cluster picker and **Open box plots**, which opens the tab on the
  picked cluster (the one clicked last, or the single selected cluster in the legend).
- The tab closes like any other. The **+** menu opens it again (**Box plots:** and the run's id)
  on the cluster it showed last, with the same marker split by group.
- Its head has a cluster picker, which switches the cluster in place, and **Show in the plot**,
  which opens the run's plot with that cluster selected.
- The charts take the tab's width. From 960 px the markers' chart runs down the left half and the
  cells per group sit over the one-marker chart on the right; narrower, they stack in one column.

## What it shows

**Header.** The cluster's colour and number, its cells and their share of the run, and its nugget
count.

**Cells per group.** One bar per sample group, labelled with the cluster's cells in that group and
their share of the group's kept cells. A run without groups has one bar per file. These
counts are exact: a nugget's weight is the number of cells it holds, so the cluster's cells in a
file are the sum of its nuggets' weights there, which is what `cluster_summary.csv` and Compare
report.

**Markers: the cluster and the rest.** One row per marker with two horizontal boxes: the
cluster's, over every sampled cell of the cluster with groups pooled (the distribution with no
treatment split), and below it, hollow, the rest of the run's, over every sampled cell of the
other clusters. A marker gets ↑ when the cluster's median is above the rest's upper quartile and
↓ when it is below the rest's lower quartile: the cluster is high or low in it against the rest of
the run. Without an arrow, the cluster's median is inside the rest's middle half. The scale is
along the top, because the chart runs to a row per marker. Click a marker's row to show it in the
next chart.

**One marker by group.** A marker picker, then one box for the cluster's cells, one per
group in the cluster (per file without groups) in the group colours Compare uses, and the rest of
the run's, hollow, last.

**The numbers.** Every box carries its numbers four ways:

- Beside it, in a column at the chart's right edge: its median, then its quartiles in brackets,
  to three significant digits, or as whole numbers from 100 up (`1.23 [0.812, 1.6]`,
  `-0.0457 [-1.23, 12,346]`).
- Its sampled cells: `n` in the markers chart's key (every marker's cluster box is drawn from the
  same cells, and so is every rest box), and in brackets after each row's name in the one-marker
  chart.
- Hovering it shows a label with its name, median, quartiles, whiskers and sampled cells to four
  significant digits. Plotly's own box hover labels each of the five numbers separately and piles
  them on a horizontal box, so the boxes take no hover; `BOX_HOVER_POINTS` (24) invisible points
  along each box, whisker to whisker, carry its label and its click.
- A table under each box chart: per marker the cluster's and the rest's median and Q1 to Q3, and
  for the picked marker each row's cells, median, Q1 to Q3 and whiskers. A row with too few cells
  for a box shows its count and a dash.

Hovering a box also writes its numbers in the line under its chart; with the pointer off the
chart, that line shows the picked marker. The line stays at the foot of the window while the
marker chart scrolls past.

Values are in the units the plot shows: the run's Transform stage (the tables undo the Scale
stage). The section's note names them.

## Where the boxes come from

The boxes are drawn from `cells.csv`, the cells the run sampled: up to `cells_per_file` per kept
file (2,000 by default), uniform without replacement. Taking the same number from every file
under-represents the large ones, so each sampled cell counts as `kept_f / sampled_f` cells, with
`kept_f` the file's kept cells (the sum of its nuggets' weights) and `sampled_f` its cells in the
payload. Within one file the weights are equal and the box is the file's own. The rest's boxes use
the same weights, so a marker's two boxes are on one footing.

- Quartiles are weighted midpoint quantiles. With the values sorted and `C_i` the running sum of
  the weights `w_i` out of a total `W`, value `i` sits at `p_i = (C_i - w_i / 2) / W`; quantile
  `q` interpolates linearly between the values whose `p` brackets it, and is the first or last
  value outside `[p_1, p_n]`. With equal weights this is the Hazen rule, `p_i = (i - 0.5) / n`.
- Whiskers reach the most extreme sampled values within 1.5 IQR of the box (Tukey). Points beyond
  them are not drawn. An interpolated quartile can sit in a gap with no value between it and its
  fence; that whisker then stays at the box edge rather than pointing into the box.
- A box needs at least `BOX_MIN_CELLS` sampled cells (5). A group with fewer draws no box; its
  label still shows its count and a note names it. A rest with fewer (a run of one cluster) draws no
  rest boxes and no arrows.
- A run made with `cells_per_file = 0` has no `cells.csv`; the tab shows the counts and says why
  it has no boxes.

## Marker sizes by weight

**Size by nugget weight** is on by default for nuggets. Nugget weights are heavy-tailed: in the
four PBMC files of the r3 fixture the median nugget holds 3 cells, the 95th percentile 106 and the
largest 3,970. A size proportional to `sqrt(w / wmax)` drew 95% of those nuggets between 6.5 and
9.4 px, so they looked alike. The diameter now follows `ln(1 + w) / ln(1 + wmax)`:

    size = factor x (min + span x ln(1 + w) / ln(1 + wmax))

with `min` 3 and `span` 21 px in 2D (2 and 12 in 3D; Pairs takes the 2D sizes x 7 / 12), and
`factor` the large-run shrink times Point size, as for every nugget marker. On r3, at Point size 1
and before the large-run shrink, that spreads the median, 95th percentile and largest nuggets to
about 6.5, 15 and 24 px. Under the switch, a size
key draws a circle per power of ten up to the largest weight, and the largest weight itself, at
the sizes the plot uses.

## Nuggets grow as the view zooms in

Zooming a 2D nuggets view in from Fit (the wheel or Box zoom; Back returns to an earlier view and
its sizes) grows every nugget, by weight or not, by

    grow = clamp((min(fit_x / view_x, fit_y / view_y)) ^ power, 1, max)

with `fit_x` and `view_x` the x axis's span at Fit and now, and `ZOOM_GROW` setting `power` to 0.5
and `max` to 4. The square root grows a dot's area with the zoom while the gaps between dots grow
with its square, so zooming in still pulls a cluster's nuggets apart; at 4x they are twice as
wide, and they stop growing at 16x. The smaller of the two axes' zooms is used, so a box drawn
tall and thin does not grow the dots past the room the view gives them across. Zooming out past
Fit leaves the sizes alone. Fit, or a double-click, autoranges the axes and resets the factor to
1; Plotly pads an autorange for the markers' size, so a Fit taken while the dots are grown is
autoranged again at 1x and fits as tightly as one taken at 1x. A new figure (another view, source
or axes) starts at 1. Pairs and cells keep their sizes. The size key shows the grown sizes.

In 3D the wheel zooms the box rather than the camera. Each wheel step narrows all three axes'
ranges about the point under the cursor, as the 2D wheel narrows two: the point keeps its place on
screen, the points around it spread apart, and points outside the narrowed box are cut off at its
faces. A mouse notch zooms in or out 1.105 times, the 2D wheel's rate, and a spin is one Back step.
Without a point under the cursor the wheel zooms about the middle of the box. (Plotly's own 3D
wheel moves the camera instead, and the camera's floor, `EYE.minR`, stopped it about 1.8 times
closer than Fit, so a dense clump never came apart.) 3D nuggets grow by 2D's rule on

    grow = clamp((min(fit_x / box_x, fit_y / box_y, fit_z / box_z) x fit_d / d) ^ power, 1, max)

with `fit_x` and `box_x` the x axis's span at Fit and in the box, `fit_d` the eye-to-center
distance of Fit's camera (`DEFAULT_CAMERA`) and `d` the camera's, and the same `ZOOM_GROW`.
Turning keeps the camera's distance and panning moves the eye and the center together, so neither
changes the sizes or the box. Zooming back out to Fit's spans returns to Fit; the box never grows
past it. Fit resets the camera and the box. A new 3D figure keeps the camera but starts at Fit's
box. `ZOOM_3D` holds the wheel's rate and the narrowest box, 1/10,000 of Fit's spans.
