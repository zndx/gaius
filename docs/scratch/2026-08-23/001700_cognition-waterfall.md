# Discover EEG waterfall under Kumo

Live strip is a canvas raster: each second the image shifts left by
one column and a new column is painted on the right (no Holoviews
re-embed, no flash). 60 columns = 60s. When a vertical line has
crossed the view, Kumo advances one tick on the 1 hr scale (minute
bucket). Holoviews `Image` remains the engine still/CLI helper.
