# Drawing portfolio

Static site generator for a drawing portfolio. See `spec.md` for the full brief.

## One-time setup

```
python -m venv .venv
.venv\Scripts\activate           # Windows
pip install -r requirements.txt
```

You also need, on PATH or as noted:

- **ffmpeg / ffprobe** — video pipeline.
- **exiftool** — metadata-strip verification. The Windows build lives in
  `exiftool-13.59_64/` (git-ignored); the build finds it automatically. On other
  platforms install `exiftool` on PATH.

## Adding an artwork

One folder per artwork under `source/` (git-ignored, never published):

```
source/2026-03-cat/
  drawing.png        # or .jpg / .tiff / .tif — required
  timelapse.mp4      # optional — .mov / .m4v also accepted
  meta.toml          # optional
```

Scanned artwork can go straight in as a raw TIFF — no need to convert it
first. If the scan carries an embedded ICC colour profile (scanners almost
always tag one), the build uses it to do a real colour-managed conversion to
sRGB before stripping it, rather than blindly reinterpreting the raw values.
An unreadable/corrupt profile falls back to a plain conversion with a warning
instead of failing the build.

`meta.toml`:

```toml
title = "Sleeping Cat"
date = 2026-03-14
note = "Charcoal on grey paper."
```

Anything missing falls back: title from the folder name (a leading `YYYY-MM`
or `YYYY-MM-DD` is stripped), date from the folder name or the file's mtime,
note omitted.

## Building

```
python build.py            # incremental — skips work whose output is current
python build.py --force     # re-encode everything
```

Output goes to `docs/`, which **is** committed. The build prints the total
`docs/` size against the 1 GB GitHub Pages cap.

## Publishing

```
python build.py && git add -A && git commit -m "Add <artwork>" && git push
```

GitHub repo settings: **Pages → deploy from branch → `main` → `/docs`**.

## Design

Done, from the first six paintings. Terracotta accent (`--accent`, sampled from
the work, used only for focus rings and link underlines), warm-paper ground,
self-hosted Newsreader at two sizes. Notes at the top of `static/site.css`.
The palette is worth a second look only if later work moves decisively away
from the warm/terracotta range.

## Still to do

- **`site.toml`** — every value is a `TODO` placeholder (artist name, tagline,
  contact address, domain). The build warns about these on every run.
- **Dates** — each `source/<slug>/meta.toml` has a title but the `date` line is
  a commented-out TODO. Add real dates: they set the grid order (newest first).
- **Custom domain** — set `domain` in `site.toml` (the build then writes
  `docs/CNAME`), and start the DNS record early.
- **git** — not a repo yet. `git init`, confirm `.gitignore` covers `source/`,
  `.venv/`, `exiftool-13.59_64/`, then push and set Pages to `main` `/docs`.
