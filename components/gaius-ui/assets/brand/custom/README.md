# Custom brand pack

Empty until an operator uploads a `.tgz` / `.tar.gz` on **Settings**.

## Accepted layouts

**Signals-style pack** (flat):

```
brand.json     # { "id", "display_name", "logo_file", "logo_alt" }
logo.svg       # required — mono-white / light mark for dark chrome
favicon.svg    # required
```

**Weathership site kit** (`~/local/src/wxs/site/brand/`):

```
brand.json                 # optional; synthesized if missing
logo/lockup/lockup-mono-white.svg   → logo.svg
favicon/favicon.svg                 → favicon.svg
logo/mark/mark-mono-white.svg       → mark.svg (optional)
```

Rules from Weathership usage guidelines: no recolor, no stretch, no
effects. Dark chrome uses the **mono-white** lockup. Keep SVG masters.

Then apply **Custom** on Settings, or `GAIUS_UI_BRAND=custom`.
