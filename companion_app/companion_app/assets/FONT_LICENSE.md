# Fallout Webfont Vendoring

## Source

The font `jh_fallout-webfont.ttf` is derived from
`jh_fallout-webfont.woff` in the upstream Pip-Boy 2000 Mk I project:

<https://github.com/xird/pip-boy-2000-mk-I/blob/main/html/jh_fallout-webfont.woff>

The upstream repository ships the file without an explicit per-file
license header. The font is vendored here solely for reproducing the
visual style of the Pip-Boy CRT in this companion app. If the
upstream project later publishes explicit attribution or license
terms, mirror them in this file.

## Conversion

The `.woff` was converted to a TrueType `.ttf` exactly once, offline,
by a developer using `fontTools` (developer-time only; **not** a
runtime dependency of `companion_app`):

```sh
# In a throwaway venv, not the project venv:
pip install fonttools brotli
python - <<'PY'
from fontTools.ttLib import TTFont
f = TTFont("jh_fallout-webfont.woff")
f.flavor = None  # strip WOFF wrapper -> plain TTF
f.save("jh_fallout-webfont.ttf")
PY
```

The resulting `.ttf` is the only font asset shipped with the package.
Re-run the conversion only if the upstream `.woff` changes.
