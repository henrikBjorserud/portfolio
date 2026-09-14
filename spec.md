# Drawing portfolio — build spec

A static portfolio site for a young artist. Stills plus timelapse videos of the
same drawings. Built by a parent; the artist does not publish to it herself
(yet). Deadline is tight — prefer the boring, working version over the clever
one.

**Fill in before starting:** artist display name, contact address, custom domain.

---

## Non-goals

Do not build these. They are how this project misses its deadline.

- No CMS, no admin UI, no upload form, no database.
- No JS framework. No build step beyond the Python script.
- No client-side search, filtering, tags, or pagination.
- No analytics, cookie banner, or third-party embeds.
- No lazy-loading library — the native `loading="lazy"` attribute is enough.

## Stack

- Python 3 + Jinja2 for generation, Pillow for image processing.
- ffmpeg for video, called via `subprocess` from the build script.
- Vanilla HTML/CSS/JS output. Native `<dialog>` for the lightbox.
- GitHub Pages, deployed from branch `main`, folder `/docs`.

## Layout on disk

```
source/                 # originals, git-ignored, never modified by the build
  2026-03-cat/
    drawing.png         # or .jpg
    timelapse.mp4       # optional
    meta.toml           # optional: title, date, note
docs/                   # build output, committed — this is the published site
build.py
templates/
static/
```

A folder in `source/` is one artwork. Missing `meta.toml` means the build falls
back to the folder name for the title and the file mtime for the date. Missing
`timelapse.mp4` is fine — the artwork just renders without one.

The build is idempotent and skips work whose output is newer than its input, so
re-running after adding one drawing takes seconds rather than re-encoding
everything.

## Image pipeline

For each `drawing.*`:

1. **Strip all metadata.** Non-negotiable — phone photos of physical drawings
   carry GPS coordinates, and this site is public. Re-save through Pillow
   without the exif block, and verify with `exiftool` on a sample.
2. Full-size web version, longest edge 2000px, quality ~85.
3. Thumbnail, longest edge 800px, for the grid.
4. Record intrinsic dimensions and write them as `width`/`height` attributes so
   the grid doesn't reflow as images load.

## Video pipeline

Source is likely a Procreate export: H.264 MP4, real-time length, larger than
it needs to be. Three outputs per timelapse.

**Full version** — what plays in the lightbox. Speed it up, but not into
meaninglessness; the point of a timelapse here is that a person can watch a
human make decisions, including the undos and false starts. Target roughly
60–90 seconds of final runtime, and cap the rate at about 15–20x. Strip audio.

```
ffmpeg -i in.mp4 -filter:v "setpts=PTS/16" -an \
  -c:v libx264 -preset slow -crf 23 -vf scale=-2:720 \
  -movflags +faststart out.mp4
```

`-movflags +faststart` matters: without it the browser downloads the whole file
before the first frame appears.

**Loop preview** — the final 4–6 seconds, same encode settings, for the grid
tile. Muted autoplay loop. Ends at the same point as the poster frame (below)
rather than a mid-process crop, so the tile never looks rougher than the
finished piece it's previewing.

**Poster frame** — the final frame, not the first. A blank canvas is a bad
thumbnail. `-sseof -1` grabs the end.

Keep every output under ~10 MB. See the deployment budget below.

## Page structure

One page. In order:

1. Small header: artist name, one line about who she is. No hero image, no
   full-viewport anything — the work should be visible without scrolling.
2. The grid of artworks. CSS `grid` with `repeat(auto-fill, minmax(...))`.
   Tiles with a timelapse show the muted loop; tiles without show the still.
3. About and contact, at the bottom.

Clicking a tile opens a native `<dialog>` containing the full-size image and,
where one exists, the full timelapse **with `controls`** — the viewer needs to
be able to scrub, pause, and rewatch. Not an autoplay loop.

Escape closes it. Focus moves into the dialog on open and returns to the tile on
close. Arrow keys move between artworks.

## Design direction

Deliberately underspecified: **look at the actual drawings before choosing a
palette.** The one firm principle is that the interface stays quiet and the
artwork carries all the colour on the page. A near-neutral ground, generous
space between tiles, one typeface used at two or three sizes.

Resist the urge to make the site itself expressive. A busy frame competes with
the work inside it, and the work is the point. Whatever accent colour the site
needs, pull it from the drawings rather than inventing one.

Choose the typeface deliberately rather than defaulting to the usual system
stack, but choose once and move on — this is not where the remaining hours
should go.

## Quality floor

- Works down to a phone screen. The grid is the only thing that needs to reflow.
- Visible keyboard focus. The lightbox is reachable and dismissable by keyboard.
- `prefers-reduced-motion` disables the autoplay loop previews and shows poster
  frames instead.
- `alt` text on every image, taken from the artwork title.
- Site is legible and navigable with JS disabled: the grid renders, the lightbox
  degrades to a direct link to the full image.

## Deployment

Build outputs to `docs/`, which is committed. Repo settings: Pages → deploy from
branch → `main` → `/docs`. Publishing is `python build.py && git add -A && git
commit && git push`. Nothing else.

No GitHub Actions workflow. It can be added later; it is not needed now.

**Budget:** published sites are capped at 1 GB and individual files at 100 MB.
At the encode settings above, roughly a hundred artworks fit comfortably. Have
the build print total output size at the end so the ceiling is never a surprise.

Custom domain: CNAME to `<username>.github.io`, plus a `CNAME` file in `docs/`.
Start the DNS record early — propagation is the one step that can't be hurried.

## Contact and privacy

- Contact goes to an address the parent controls, not the artist's own.
- Display name only, not a full legal name.
- The repo is public, so anything in `source/` that gets committed is public.
  Verify `.gitignore` covers `source/` and `.venv/` before the first push.

## Done when

- [ ] `python build.py` on a clean checkout produces a working `docs/`.
- [ ] `exiftool` on a built image shows no GPS or camera data.
- [ ] Grid and lightbox work on a phone.
- [ ] A timelapse plays, scrubs, and can be replayed.
- [ ] Total `docs/` size is printed and is well under 1 GB.
- [ ] Site loads over the custom domain with a valid certificate.
