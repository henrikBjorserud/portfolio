#!/usr/bin/env python3
"""Static portfolio builder.

Reads originals from source/, writes the published site to docs/.
See spec.md for the why behind every pipeline step.

Usage:
    python build.py            # incremental build
    python build.py --force    # rebuild every derivative
"""

from __future__ import annotations

import argparse
import io
import json
import re
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image, ImageCms, ImageOps

ROOT = Path(__file__).parent.resolve()
SOURCE = ROOT / "source"
DOCS = ROOT / "docs"
TEMPLATES = ROOT / "templates"
STATIC = ROOT / "static"
SITE_TOML = ROOT / "site.toml"

IMAGE_NAMES = ["drawing.png", "drawing.jpg", "drawing.jpeg", "drawing.tiff", "drawing.tif"]
VIDEO_NAMES = ["timelapse.mp4", "timelapse.mov", "timelapse.m4v"]

FULL_EDGE = 2000      # longest edge of the web-size image
THUMB_EDGE = 800      # longest edge of the grid thumbnail
IMAGE_QUALITY = 85    # WebP quality for full + thumb

VIDEO_TARGET_SECONDS = 75    # aim for 60-90s of final runtime
VIDEO_MAX_RATE = 20          # never speed up more than this
VIDEO_MIN_RATE = 1
PREVIEW_SECONDS = 5          # grid loop preview length
VIDEO_HEIGHT = 720

SIZE_WARN_BYTES = 10 * 1024 * 1024   # warn per-output over ~10 MB
TOTAL_BUDGET_BYTES = 1024 ** 3       # GitHub Pages hard cap: 1 GB

# Bundled Windows exiftool (see .gitignore). Falls back to PATH.
EXIFTOOL_CANDIDATES = [
    ROOT / "exiftool-13.59_64" / "exiftool(-k).exe",
    ROOT / "exiftool.exe",
]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def log(msg: str) -> None:
    print(msg, flush=True)


def _force_utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=True
    )


def newer_than_all(output: Path, *inputs: Path) -> bool:
    """True when output exists and is at least as new as every input."""
    if not output.exists():
        return False
    out_m = output.stat().st_mtime
    return all(i.exists() and i.stat().st_mtime <= out_m for i in inputs)


def human_size(n: float) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:,.1f} {unit}"
        size /= 1024
    return f"{size:,.1f} GB"


def dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def find_exiftool() -> Path | str | None:
    for cand in EXIFTOOL_CANDIDATES:
        if cand.exists():
            return cand
    if shutil.which("exiftool"):
        return "exiftool"
    return None


# --------------------------------------------------------------------------- #
# model
# --------------------------------------------------------------------------- #

@dataclass
class Artwork:
    slug: str
    title: str
    day: date
    note: str = ""
    image: dict = field(default_factory=dict)
    video: dict | None = None

    def as_json(self) -> dict:
        return {"title": self.title, "image": self.image, "video": self.video}


TITLE_PREFIX_RE = re.compile(r"^\d{4}-\d{2}(-\d{2})?[-_ ]+")


def read_meta(folder: Path) -> tuple[str, date, str]:
    """(title, date, note) with folder-name / mtime fallbacks."""
    title = TITLE_PREFIX_RE.sub("", folder.name).replace("-", " ").replace("_", " ").strip()
    title = title[:1].upper() + title[1:] if title else folder.name
    day: date | None = None
    note = ""

    meta_path = folder / "meta.toml"
    if meta_path.exists():
        meta = tomllib.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("title"):
            title = str(meta["title"])
        note = str(meta.get("note", ""))
        raw = meta.get("date")
        if isinstance(raw, (date, datetime)):
            day = raw.date() if isinstance(raw, datetime) else raw
        elif isinstance(raw, str) and raw.strip():
            day = date.fromisoformat(raw.strip())

    if day is None:
        m = re.match(r"^(\d{4})-(\d{2})(?:-(\d{2}))?", folder.name)
        if m:
            y, mo, d = int(m[1]), int(m[2]), int(m[3] or 1)
            try:
                day = date(y, mo, d)
            except ValueError:
                day = None

    if day is None:
        candidates = [folder / n for n in IMAGE_NAMES + VIDEO_NAMES]
        src = next((c for c in candidates if c.exists()), folder)
        day = date.fromtimestamp(src.stat().st_mtime)

    return title, day, note


# --------------------------------------------------------------------------- #
# image pipeline
# --------------------------------------------------------------------------- #

def _normalize_to_srgb(im: Image.Image, src: Path) -> Image.Image:
    """Bake in rotation and land in plain sRGB, regardless of source quirks.

    Phone JPEGs are effectively already sRGB, so a blind mode convert is fine
    for them. Scanner TIFFs are not — they often carry a scanner- or
    software-specific ICC profile, and reinterpreting those raw channel
    values as if they were sRGB (what a blind .convert("RGB") does) visibly
    shifts colour. If a profile is embedded, use it to do a real conversion;
    only fall back to the blind convert when there is no profile to convert
    from, or the embedded one turns out to be unreadable.
    """
    im = ImageOps.exif_transpose(im)

    icc = im.info.get("icc_profile")
    if icc:
        try:
            src_profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            srgb_profile = ImageCms.createProfile("sRGB")
            mode = "RGBA" if "A" in im.getbands() else "RGB"
            converted = ImageCms.profileToProfile(im, src_profile, srgb_profile, outputMode=mode)
            log(f"    colour: converted embedded profile -> sRGB ({src.name})")
            return converted.convert("RGB")
        except Exception as e:  # malformed/unsupported profile — don't fail the build over it
            log(f"    WARNING: embedded colour profile unreadable ({e}); treating as sRGB")

    return im.convert("RGB")


def _save_clean(im: Image.Image, dest: Path, edge: int) -> tuple[int, int]:
    """Downscale to `edge` and write a WebP with no metadata at all.

    Pasting the pixels into a brand-new image drops every ancillary chunk —
    exif (GPS included), ICC profile, XMP, comments — because the new image
    has an empty .info dict and we pass no exif= on save. WebP over JPEG:
    30-45% smaller at the same quality setting for this kind of painterly
    source (measured directly, not assumed), with no fallback needed — every
    browser this site will hit has supported it for years.
    """
    resized = im.copy()
    resized.thumbnail((edge, edge), Image.LANCZOS)
    clean = Image.new("RGB", resized.size)
    clean.paste(resized)
    clean.save(dest, "WEBP", quality=IMAGE_QUALITY, method=6)
    return clean.size


def process_image(src: Path, out_dir: Path, force: bool) -> dict:
    full_path = out_dir / "full.webp"
    thumb_path = out_dir / "thumb.webp"

    if not force and newer_than_all(full_path, src) and newer_than_all(thumb_path, src):
        with Image.open(full_path) as fim:
            fw, fh = fim.size
        with Image.open(thumb_path) as tim:
            tw, th = tim.size
    else:
        with Image.open(src) as im:
            im = _normalize_to_srgb(im, src)

            fw, fh = _save_clean(im, full_path, FULL_EDGE)
            tw, th = _save_clean(im, thumb_path, THUMB_EDGE)

        log(f"    image: full {fw}x{fh}, thumb {tw}x{th}")

    return {
        "full": rel(full_path),
        "thumb": rel(thumb_path),
        "full_width": fw, "full_height": fh,
        "thumb_width": tw, "thumb_height": th,
    }


# --------------------------------------------------------------------------- #
# video pipeline
# --------------------------------------------------------------------------- #

def probe_duration(src: Path) -> float:
    cp = run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nk=1:nw=1", str(src),
    ])
    return float(cp.stdout.strip())


def probe_size(src: Path) -> tuple[int, int]:
    cp = run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(src),
    ])
    w, h = cp.stdout.strip().split("x")
    return int(w), int(h)


def even(n: int) -> int:
    return n - (n % 2)


def process_video(src: Path, out_dir: Path, force: bool) -> dict:
    full_path = out_dir / "timelapse.mp4"
    preview_path = out_dir / "preview.mp4"
    poster_path = out_dir / "poster.jpg"

    duration = probe_duration(src)
    rate = max(VIDEO_MIN_RATE, min(VIDEO_MAX_RATE, round(duration / VIDEO_TARGET_SECONDS)))
    final_runtime = duration / rate
    log(f"    video: source {duration:.0f}s -> {rate}x -> {final_runtime:.0f}s final")

    common_out = [
        "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "23",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
    ]

    if force or not newer_than_all(full_path, src):
        run([
            "ffmpeg", "-y", "-i", str(src),
            "-filter:v", f"setpts=PTS/{rate},scale=-2:{VIDEO_HEIGHT}",
            *common_out, str(full_path),
        ])

    if force or not newer_than_all(preview_path, src):
        seg = PREVIEW_SECONDS * rate
        start = max(0.0, duration / 2 - seg / 2)
        seg = min(seg, max(0.5, duration - start))
        run([
            "ffmpeg", "-y", "-ss", f"{start:.3f}", "-t", f"{seg:.3f}", "-i", str(src),
            "-filter:v", f"setpts=PTS/{rate},scale=-2:{VIDEO_HEIGHT}",
            *common_out, str(preview_path),
        ])

    if force or not newer_than_all(poster_path, src):
        # last frame, not the first — a blank canvas is a bad thumbnail
        run([
            "ffmpeg", "-y", "-sseof", "-3", "-i", str(src),
            "-vf", f"scale=-2:{VIDEO_HEIGHT}", "-update", "1", "-frames:v", "1",
            "-q:v", "3", str(poster_path),
        ])

    pw, ph = probe_size(preview_path)
    for p in (full_path, preview_path):
        if p.stat().st_size > SIZE_WARN_BYTES:
            log(f"    WARNING: {p.name} is {human_size(p.stat().st_size)} (>~10 MB)")

    return {
        "full": rel(full_path),
        "preview": rel(preview_path),
        "poster": rel(poster_path),
        "preview_width": even(pw), "preview_height": even(ph),
    }


# --------------------------------------------------------------------------- #
# assembly
# --------------------------------------------------------------------------- #

def rel(path: Path) -> str:
    return path.relative_to(DOCS).as_posix()


def _safe_json(obj) -> str:
    """JSON safe to drop straight into a <script> element."""
    return (
        json.dumps(obj, separators=(",", ":"))
        .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    )


def load_site() -> dict:
    if not SITE_TOML.exists():
        sys.exit("site.toml is missing.")
    cfg = tomllib.loads(SITE_TOML.read_text(encoding="utf-8"))
    todos = [k for k, v in cfg.items() if isinstance(v, str) and v.startswith("TODO")]
    if todos:
        log(f"NOTE: site.toml still has placeholders: {', '.join(todos)}")
    return cfg


def collect_artworks(force: bool) -> list[Artwork]:
    if not SOURCE.exists():
        SOURCE.mkdir()
        log(f"created empty {rel_root(SOURCE)}/ — add one folder per artwork")
        return []

    artworks: list[Artwork] = []
    for folder in sorted(p for p in SOURCE.iterdir() if p.is_dir() and not p.name.startswith(".")):
        img_src = next((folder / n for n in IMAGE_NAMES if (folder / n).exists()), None)
        if img_src is None:
            log(f"  skip {folder.name}: no drawing.png/.jpg")
            continue

        title, day, note = read_meta(folder)
        out_dir = DOCS / "art" / folder.name
        out_dir.mkdir(parents=True, exist_ok=True)
        log(f"  {folder.name}  \"{title}\"  {day.isoformat()}")

        art = Artwork(slug=folder.name, title=title, day=day, note=note)
        art.image = process_image(img_src, out_dir, force)

        vid_src = next((folder / n for n in VIDEO_NAMES if (folder / n).exists()), None)
        if vid_src is not None:
            art.video = process_video(vid_src, out_dir, force)

        artworks.append(art)

    artworks.sort(key=lambda a: a.day, reverse=True)
    prune_orphans({a.slug for a in artworks})
    return artworks


def prune_orphans(live_slugs: set[str]) -> None:
    """Delete docs/art/<slug>/ folders whose source folder is gone."""
    art_root = DOCS / "art"
    if not art_root.exists():
        return
    for d in art_root.iterdir():
        if d.is_dir() and d.name not in live_slugs:
            shutil.rmtree(d)
            log(f"  pruned stale output: art/{d.name}/")


def rel_root(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def verify_metadata_stripped(artworks: list[Artwork]) -> None:
    tool = find_exiftool()
    if not tool:
        log("NOTE: exiftool not found — cannot verify metadata stripping. "
            "Install it and re-run before the first push (see spec.md).")
        return
    if not artworks:
        return

    # Check every built image, not a sample — one stray original is the whole risk.
    images = [DOCS / a.image["full"] for a in artworks] + [DOCS / a.image["thumb"] for a in artworks]
    for img in images:
        cp = subprocess.run(
            [str(tool), "-G1", "-s", "-a",
             "-GPS:all", "-Make", "-Model", "-SerialNumber",
             "-DateTimeOriginal", "-CreateDate", "-XMP:all", str(img)],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
        )
        leaked = [ln for ln in cp.stdout.splitlines() if ln.strip()]
        if leaked:
            sys.exit(f"METADATA LEAK in {img.relative_to(DOCS).as_posix()}:\n" + "\n".join(leaked))
    log(f"  exiftool: {len(images)} built image(s) clean (no GPS / camera / XMP data)")


def render(site: dict, artworks: list[Artwork]) -> None:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True, lstrip_blocks=True,
    )
    tpl = env.get_template("index.html.j2")
    html = tpl.render(
        site=site,
        artworks=[
            {"title": a.title, "note": a.note, "image": a.image, "video": a.video}
            for a in artworks
        ],
        artworks_json=_safe_json([a.as_json() for a in artworks]),
    )
    (DOCS / "index.html").write_text(html, encoding="utf-8", newline="\n")

    shutil.copytree(STATIC, DOCS / "static", dirs_exist_ok=True)
    (DOCS / ".nojekyll").write_text("", encoding="utf-8")

    domain = site.get("domain", "")
    if domain and not domain.startswith("TODO"):
        (DOCS / "CNAME").write_text(domain + "\n", encoding="utf-8", newline="\n")
    else:
        log(f"NOTE: no CNAME written — set 'domain' in site.toml "
            f"(then point DNS at {site.get('github_pages_host', '<username>.github.io')}).")


def report_size() -> None:
    total = dir_size(DOCS)
    pct = total / TOTAL_BUDGET_BYTES * 100
    log("")
    log(f"docs/ total: {human_size(total)}  ({pct:.1f}% of the 1 GB Pages cap)")
    if total > TOTAL_BUDGET_BYTES * 0.8:
        log("WARNING: approaching the 1 GB ceiling.")


# --------------------------------------------------------------------------- #

def main() -> None:
    _force_utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="rebuild all derivatives")
    args = ap.parse_args()

    DOCS.mkdir(exist_ok=True)
    site = load_site()

    log("scanning source/ ...")
    artworks = collect_artworks(args.force)
    log(f"{len(artworks)} artwork(s)")

    render(site, artworks)
    verify_metadata_stripped(artworks)
    report_size()
    log("\ndone -> docs/")


if __name__ == "__main__":
    main()
