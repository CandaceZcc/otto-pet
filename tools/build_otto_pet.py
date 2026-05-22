#!/usr/bin/env python3
"""Build the 电棍otto Codex pet from the source GIF clips."""

from __future__ import annotations

import json
import math
import shutil
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter, ImageSequence, ImageStat

try:
    from rembg import new_session, remove
except ImportError:  # pragma: no cover - optional dependency
    new_session = None
    remove = None


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "pet-build"
FRAMES = BUILD / "frames"
FINAL = BUILD / "final"
QA = BUILD / "qa"
PACKAGE = BUILD / "package" / "diangun-otto"
DIST = ROOT / "pet" / "diangun-otto"

CELL_W = 192
CELL_H = 208
ATLAS_COLS = 8
ATLAS_ROWS = 9

ROWS = [
    ("idle", 0, 6),
    ("running-right", 1, 8),
    ("running-left", 2, 8),
    ("waving", 3, 4),
    ("jumping", 4, 5),
    ("failed", 5, 8),
    ("waiting", 6, 6),
    ("running", 7, 6),
    ("review", 8, 6),
]


@dataclass(frozen=True)
class SourceClip:
    key: str
    filename: str
    background: str


SOURCES = {
    "failed": SourceClip("failed", "fail.gif", "black"),
    "running_lowres": SourceClip("running_lowres", "running.gif", "black"),
    "waiting": SourceClip("waiting", "waiting.gif", "black"),
    "suona": SourceClip("suona", "吹唢呐(可以作为running中的一个环节).gif", "black"),
    "jiyan_running": SourceClip("jiyan_running", "急眼2（待定）.gif", "black"),
    "jiyan_review": SourceClip("jiyan_review", "急眼（待定）.gif", "black"),
}


STATE_SOURCES = {
    "idle": ("suona", [4, 5, 6, 7, 6, 5], "visible looping suona idle performance"),
    "running-right": (
        "jiyan_running",
        [26, 27, 28, 29, 30, 31, 32, 33],
        "continuous urgent work loop with slight right drift",
    ),
    "running-left": (
        "jiyan_running",
        [26, 27, 28, 29, 30, 31, 32, 33],
        "mirrored continuous urgent work loop with slight left drift",
    ),
    "waving": ("waiting", [0, 1, 2, 3], "previous idle baseline moved into waving row as a smooth micro-loop"),
    "jumping": ("waiting", [19, 20, 21, 22, 23], "smooth vertical bob rebuilt from nearby waiting frames"),
    "failed": ("failed", [10, 11, 12, 13, 14, 15, 16, 17], "smooth failed reaction"),
    "waiting": ("waiting", [19, 20, 21, 22, 23, 24], "smooth waiting for input loop"),
    "running": (
        "jiyan_running",
        [29, 30, 31, 32, 33, 34],
        "smooth high-intensity processing loop from 急眼2",
    ),
    "review": ("jiyan_review", [18, 19, 20, 21, 22, 23], "smooth focused review loop from 急眼"),
}


IDLE_SEQUENCE = [
    ("suona", 4, 1.0, 0, 0, True, "visible looping suona idle performance"),
    ("suona", 5, 1.0, 0, 0, True, "visible looping suona idle performance"),
    ("running_lowres", 0, 1.08, 0, 0, False, "brief p2 wheelchair idle flash"),
    ("suona", 7, 1.0, 0, 0, True, "visible looping suona idle performance"),
    ("running_lowres", 14, 1.08, 0, 0, False, "brief p2 wheelchair idle flash"),
    ("suona", 5, 1.0, 0, 0, True, "visible looping suona idle performance"),
]


def reset_output() -> None:
    if BUILD.exists():
        shutil.rmtree(BUILD)
    for directory in [FRAMES, FINAL, QA / "previews", PACKAGE]:
        directory.mkdir(parents=True, exist_ok=True)


def load_gif_frames(path: Path) -> list[Image.Image]:
    with Image.open(path) as opened:
        return [frame.convert("RGBA") for frame in ImageSequence.Iterator(opened)]


def ai_segment_frame(frame: Image.Image, session: object | None) -> Image.Image | None:
    if remove is None or session is None:
        return None
    try:
        segmented = remove(frame.convert("RGBA"), session=session, post_process_mask=True)
    except Exception:
        return None
    return clear_transparent_rgb(segmented.convert("RGBA"))


def sample_background(frame: Image.Image, kind: str) -> tuple[int, int, int]:
    rgb = frame.convert("RGB")
    w, h = rgb.size
    samples = []
    margin = max(4, min(w, h) // 18)
    boxes = [
        (0, 0, w, margin),
        (0, h - margin, w, h),
        (0, 0, margin, h),
        (w - margin, 0, w, h),
    ]
    for box in boxes:
        crop = rgb.crop(box)
        samples.extend(crop.getdata())

    if kind == "white":
        candidates = [px for px in samples if min(px) > 160]
        if not candidates:
            candidates = samples
    else:
        candidates = [px for px in samples if max(px) < 70]
        if not candidates:
            candidates = samples

    channels = list(zip(*candidates))
    return tuple(int(sorted(channel)[len(channel) // 2]) for channel in channels)  # type: ignore[return-value]


def matte_from_background(frame: Image.Image, kind: str) -> Image.Image:
    rgba = frame.convert("RGBA")
    bg = sample_background(rgba, kind)
    rgb = rgba.convert("RGB")
    diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, bg)).convert("L")

    if kind == "white":
        # White-background source has lower contrast around skin, so use a tighter color test.
        alpha = diff.point(lambda v: 0 if v < 24 else min(255, max(0, (v - 24) * 5)))
    else:
        alpha = diff.point(lambda v: 0 if v < 18 else min(255, max(0, (v - 18) * 7)))

    alpha = alpha.filter(ImageFilter.MedianFilter(3))
    alpha = alpha.filter(ImageFilter.GaussianBlur(0.35))

    # Drop tiny disconnected background flecks by keeping the central/lower subject bounds.
    bbox = alpha.point(lambda v: 255 if v > 30 else 0).getbbox()
    cleaned = rgba.copy()
    cleaned.putalpha(alpha)
    if bbox:
        mask = Image.new("L", alpha.size, 0)
        pad = 8
        box = (
            max(0, bbox[0] - pad),
            max(0, bbox[1] - pad),
            min(alpha.size[0], bbox[2] + pad),
            min(alpha.size[1], bbox[3] + pad),
        )
        mask.paste(255, box)
        cleaned.putalpha(ImageChops.multiply(alpha, mask))
    return clear_transparent_rgb(cleaned)


def clear_transparent_rgb(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    data = bytearray(rgba.tobytes())
    for index in range(0, len(data), 4):
        if data[index + 3] == 0:
            data[index] = data[index + 1] = data[index + 2] = 0
    return Image.frombytes("RGBA", rgba.size, bytes(data))


def solidify_subject_alpha(image: Image.Image) -> Image.Image:
    """Make the subject opaque while preserving a narrow antialiased edge."""
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    strong = alpha.point(lambda v: 255 if v >= 42 else 0)
    if strong.getbbox() is None:
        return clear_transparent_rgb(rgba)

    interior = strong.filter(ImageFilter.MinFilter(3))
    edge = strong.filter(ImageFilter.MaxFilter(3))
    soft_edge = edge.filter(ImageFilter.GaussianBlur(0.45))
    edge_alpha = ImageChops.subtract(soft_edge, interior)
    normalized = ImageChops.lighter(interior, edge_alpha)
    normalized = normalized.point(lambda v: 255 if v >= 190 else (0 if v < 20 else v))
    rgba.putalpha(normalized)
    return clear_transparent_rgb(rgba)


def keep_largest_alpha_component(image: Image.Image, *, solidify: bool = True) -> Image.Image:
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    mask = alpha.point(lambda v: 255 if v > 18 else 0)
    w, h = mask.size
    pixels = mask.load()
    seen = bytearray(w * h)
    components: list[tuple[int, tuple[int, int, int, int], list[int]]] = []

    for y in range(h):
        for x in range(w):
            offset = y * w + x
            if seen[offset] or pixels[x, y] == 0:
                continue
            stack = [(x, y)]
            seen[offset] = 1
            indexes: list[int] = []
            min_x = max_x = x
            min_y = max_y = y
            while stack:
                cx, cy = stack.pop()
                indexes.append(cy * w + cx)
                min_x = min(min_x, cx)
                max_x = max(max_x, cx)
                min_y = min(min_y, cy)
                max_y = max(max_y, cy)
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if nx < 0 or ny < 0 or nx >= w or ny >= h:
                        continue
                    n_offset = ny * w + nx
                    if seen[n_offset] or pixels[nx, ny] == 0:
                        continue
                    seen[n_offset] = 1
                    stack.append((nx, ny))
            components.append((len(indexes), (min_x, min_y, max_x + 1, max_y + 1), indexes))

    if not components:
        return rgba

    largest_area = max(area for area, _box, _indexes in components)
    keep_indexes: set[int] = set()
    for area, _box, indexes in components:
        if area == largest_area:
            keep_indexes.update(indexes)

    alpha_data = bytearray(alpha.tobytes())
    for index in range(len(alpha_data)):
        if index not in keep_indexes:
            alpha_data[index] = 0
    rgba.putalpha(Image.frombytes("L", (w, h), bytes(alpha_data)))
    if solidify:
        return solidify_subject_alpha(rgba)
    return clear_transparent_rgb(rgba)


def subject_bbox(frames: list[Image.Image], threshold: int = 18) -> tuple[int, int, int, int]:
    union: tuple[int, int, int, int] | None = None
    for frame in frames:
        alpha = frame.getchannel("A").point(lambda v: 255 if v > threshold else 0)
        bbox = alpha.getbbox()
        if not bbox:
            continue
        if union is None:
            union = bbox
        else:
            union = (
                min(union[0], bbox[0]),
                min(union[1], bbox[1]),
                max(union[2], bbox[2]),
                max(union[3], bbox[3]),
            )
    return union or (0, 0, frames[0].width, frames[0].height)


def fit_to_cell(
    frame: Image.Image,
    viewport: tuple[int, int, int, int],
    *,
    scale: float = 1.0,
    x_shift: int = 0,
    y_shift: int = 0,
    mirror: bool = False,
    isolate_largest_component: bool = True,
) -> Image.Image:
    crop = frame.crop(viewport)
    if mirror:
        crop = crop.transpose(Image.Transpose.FLIP_LEFT_RIGHT)

    alpha_bbox = crop.getchannel("A").point(lambda v: 255 if v > 18 else 0).getbbox()
    if alpha_bbox:
        crop = crop.crop(alpha_bbox)

    max_w = int(CELL_W * 0.88 * scale)
    max_h = int(CELL_H * 0.86 * scale)
    crop.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)

    canvas = Image.new("RGBA", (CELL_W, CELL_H), (0, 0, 0, 0))
    left = (CELL_W - crop.width) // 2 + x_shift
    top = CELL_H - crop.height - 10 + y_shift
    canvas.alpha_composite(crop, (left, top))
    canvas = clear_transparent_rgb(canvas)
    if isolate_largest_component:
        return keep_largest_alpha_component(canvas, solidify=False)
    return canvas


def brightness(frame: Image.Image) -> float:
    alpha = frame.getchannel("A")
    bbox = alpha.point(lambda v: 255 if v > 20 else 0).getbbox()
    if not bbox:
        return 0.0
    crop = frame.crop(bbox).convert("L")
    mask = alpha.crop(bbox)
    return float(ImageStat.Stat(crop, mask=mask).mean[0])


def build_state_frames(
    state: str,
    cleaned: dict[str, list[Image.Image]],
    viewports: dict[str, tuple[int, int, int, int]],
) -> list[dict[str, object]]:
    if state == "idle":
        output = []
        for source_key, source_index, scale, x_shift, y_shift, isolate, note in IDLE_SEQUENCE:
            frames = cleaned[source_key]
            source_index = min(source_index, len(frames) - 1)
            cell = fit_to_cell(
                frames[source_index],
                viewports[source_key],
                scale=scale,
                x_shift=x_shift,
                y_shift=y_shift,
                isolate_largest_component=isolate,
            )
            output.append(
                {
                    "image": cell,
                    "source": source_key,
                    "source_frame": source_index,
                    "note": note,
                }
            )
        return output

    source_key, indexes, note = STATE_SOURCES[state]
    frames = cleaned[source_key]
    viewport = viewports[source_key]
    output = []
    for out_index, source_index in enumerate(indexes):
        source_index = min(source_index, len(frames) - 1)
        x_shift = 0
        y_shift = 0
        scale = 1.0
        mirror = False

        if state == "running-right":
            x_shift = int(math.sin(out_index / max(1, len(indexes) - 1) * math.pi * 2) * 5) + 5
        elif state == "running-left":
            mirror = True
            x_shift = -int(math.sin(out_index / max(1, len(indexes) - 1) * math.pi * 2) * 5) - 5
        elif state == "jumping":
            y_shift = [8, -6, -22, -8, 8][out_index]
            scale = 0.88
        elif state == "waving":
            scale = 1.02
        elif state == "running":
            note = "smooth high-intensity processing loop from 急眼2"

        cell = fit_to_cell(
            frames[source_index],
            viewport,
            scale=scale,
            x_shift=x_shift,
            y_shift=y_shift,
            mirror=mirror,
        )
        output.append(
            {
                "image": cell,
                "source": source_key,
                "source_frame": source_index,
                "note": note,
            }
        )
    return output


def save_frames(states: dict[str, list[dict[str, object]]]) -> dict[str, object]:
    manifest: dict[str, object] = {
        "pet": "电棍otto",
        "cell": {"width": CELL_W, "height": CELL_H},
        "states": {},
    }
    for state, frame_infos in states.items():
        state_dir = FRAMES / state
        state_dir.mkdir(parents=True, exist_ok=True)
        state_manifest = []
        for index, info in enumerate(frame_infos):
            path = state_dir / f"{index:02d}.png"
            image = info["image"]
            assert isinstance(image, Image.Image)
            image.save(path)
            state_manifest.append(
                {
                    "file": str(path.relative_to(BUILD)),
                    "source": info["source"],
                    "source_frame": info["source_frame"],
                    "note": info["note"],
                    "brightness": round(brightness(image), 2),
                }
            )
        manifest["states"][state] = state_manifest
    (FRAMES / "frames-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def compose_atlas(states: dict[str, list[dict[str, object]]]) -> Image.Image:
    atlas = Image.new("RGBA", (ATLAS_COLS * CELL_W, ATLAS_ROWS * CELL_H), (0, 0, 0, 0))
    for state, row, frame_count in ROWS:
        for column in range(frame_count):
            image = states[state][column]["image"]
            assert isinstance(image, Image.Image)
            atlas.alpha_composite(image, (column * CELL_W, row * CELL_H))
    return clear_transparent_rgb(atlas)


def make_contact_sheet(states: dict[str, list[dict[str, object]]]) -> None:
    label_w = 150
    scale = 0.55
    thumb_w = int(CELL_W * scale)
    thumb_h = int(CELL_H * scale)
    sheet = Image.new("RGB", (label_w + ATLAS_COLS * thumb_w, ATLAS_ROWS * thumb_h), "white")
    from PIL import ImageDraw

    draw = ImageDraw.Draw(sheet)
    for state, row, frame_count in ROWS:
        y = row * thumb_h
        draw.text((8, y + 8), f"{state} ({frame_count})", fill=(0, 0, 0))
        for col in range(frame_count):
            image = states[state][col]["image"]
            assert isinstance(image, Image.Image)
            bg = Image.new("RGB", (CELL_W, CELL_H), (236, 236, 236))
            bg.paste(image.convert("RGB"), mask=image.getchannel("A"))
            bg = bg.resize((thumb_w, thumb_h), Image.Resampling.LANCZOS)
            sheet.paste(bg, (label_w + col * thumb_w, y))
    sheet.save(QA / "contact-sheet.png")


def save_previews(states: dict[str, list[dict[str, object]]]) -> None:
    durations = {
        "idle": [85] * 6,
        "running-right": [110] * 8,
        "running-left": [110] * 8,
        "waving": [130, 130, 130, 130],
        "jumping": [130, 130, 130, 130, 130],
        "failed": [130] * 8,
        "waiting": [130, 130, 130, 130, 130, 130],
        "running": [110, 110, 110, 110, 110, 110],
        "review": [130, 130, 130, 130, 130, 130],
    }
    for state, frame_infos in states.items():
        frames = [info["image"] for info in frame_infos]
        assert all(isinstance(frame, Image.Image) for frame in frames)
        frames[0].save(
            QA / "previews" / f"{state}.gif",
            save_all=True,
            append_images=frames[1:],
            duration=durations[state],
            loop=0,
            disposal=2,
            optimize=False,
        )


def write_package() -> None:
    shutil.copy2(FINAL / "spritesheet.webp", PACKAGE / "spritesheet.webp")
    pet_json = {
        "id": "diangun-otto",
        "displayName": "电棍otto",
        "description": "A Codex pet built from the provided Otto meme GIF clips.",
        "spritesheetPath": "spritesheet.webp",
    }
    (PACKAGE / "pet.json").write_text(
        json.dumps(pet_json, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    DIST.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PACKAGE / "pet.json", DIST / "pet.json")
    shutil.copy2(PACKAGE / "spritesheet.webp", DIST / "spritesheet.webp")


def main() -> None:
    reset_output()

    raw = {key: load_gif_frames(ROOT / clip.filename) for key, clip in SOURCES.items()}
    segmentation_session = new_session("u2net_human_seg") if new_session is not None else None
    cleaned: dict[str, list[Image.Image]] = {}
    for key, clip in SOURCES.items():
        cleaned[key] = [
            ai_segment_frame(frame, segmentation_session) or matte_from_background(frame, clip.background)
            for frame in raw[key]
        ]

    viewports = {
        key: subject_bbox(frames)
        for key, frames in cleaned.items()
    }

    states = {
        state: build_state_frames(state, cleaned, viewports)
        for state, _row, _count in ROWS
    }
    manifest = save_frames(states)

    atlas = compose_atlas(states)
    FINAL.mkdir(parents=True, exist_ok=True)
    atlas.save(FINAL / "spritesheet.png")
    atlas.save(FINAL / "spritesheet.webp", format="WEBP", lossless=True, quality=100, method=6, exact=True)

    make_contact_sheet(states)
    save_previews(states)
    write_package()

    summary = {
        "ok": True,
        "package": str(PACKAGE),
        "dist": str(DIST),
        "spritesheet": str(PACKAGE / "spritesheet.webp"),
        "contact_sheet": str(QA / "contact-sheet.png"),
        "manifest": str(FRAMES / "frames-manifest.json"),
        "states": {state: len(items) for state, items in manifest["states"].items()},  # type: ignore[index]
    }
    (QA / "build-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
