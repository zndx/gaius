# gpu-n bivariate 1D strip (power × util)

`pwr-n` is now `gpu-n`: one packed float, one row. `util-n` unchanged
so we can iterate the combined map without a layout change.

Encoding (OKLCH, same math in `waterfall_color.py` and `discover.js`):

- **Hue** — SM util (keiretsu 250° idle → amber 48° busy)
- **Chroma** — max(|power|, 0.3·util) so watts still light the pixel
  when util is low, and util still tints when power is low
- **Lightness** — 0.55 mid so it reads on Keiretsu dark `#090b0e` and
  light `#eef1f4` (no RdBu white center)

Holoviews stills are `hv.RGB` (not RdBu Image). Canvas labels/background
use `--color-kumo-*`; `data-mode` mutation rebuilds the raster.
