"""Caption overlay for the scene renderer (video text, never baked into images).

Renderer receives: image_path, audio_path, caption_text, duration, settings.
Produces scene video = clean image + Ken Burns + caption overlay + audio.

Unicode-safe, wrapped, safe margins, lower-third (or center), semi-transparent
background + white text. Reuses Pillow only (no extra deps).
"""
from __future__ import annotations

import textwrap
from pathlib import Path

from app.core import config
from app.core.logger import log

_FONT_CANDIDATES = ("arial.ttf", "segoeui.ttf", "DejaVuSans.ttf")


def _load_font(size: int):
    from PIL import ImageFont
    import os
    for name in _FONT_CANDIDATES:
        for folder in (r"C:\Windows\Fonts", "/usr/share/fonts", "/usr/local/share/fonts"):
            p = os.path.join(folder, name)
            if os.path.exists(p):
                try:
                    return ImageFont.truetype(p, size)
                except Exception:
                    continue
    return ImageFont.load_default()


def caption_enabled() -> bool:
    return bool(config.CAPTION_ENABLED)


def wrap_caption(text: str, width_chars: int = 42) -> list[str]:
    t = " ".join(str(text or "").split())
    if not t:
        return []
    return textwrap.wrap(t, width_chars, break_long_words=False, break_on_hyphens=False)


def overlay_caption(image_path: Path | str, caption_text: str,
                    dest: Path | str | None = None,
                    font_size: int | None = None,
                    position: str | None = None,
                    max_width_ratio: float | None = None,
                    bg_opacity: int | None = None) -> Path:
    """Burn caption onto a COPY of image_path; return dest path. No-op when disabled/empty."""
    from PIL import Image, ImageDraw
    src = Path(image_path)
    if dest is None:
        dest = src.with_name(src.stem + "_captioned.png")
    dest = Path(dest)
    if not caption_enabled() or not str(caption_text or "").strip():
        if dest.resolve() != src.resolve():
            import shutil
            shutil.copyfile(str(src), str(dest))
        return dest
    font_size = font_size or config.CAPTION_FONT_SIZE
    position = position or config.CAPTION_POSITION
    max_width_ratio = max_width_ratio if max_width_ratio is not None else config.CAPTION_MAX_WIDTH_RATIO
    bg_opacity = bg_opacity if bg_opacity is not None else config.CAPTION_BG_OPACITY

    img = Image.open(str(src)).convert("RGB")
    W, H = img.size
    # Scale font with output width so mobile + 1080p stay readable.
    size = max(20, int(font_size * W / 1280))
    font = _load_font(size)
    lines = wrap_caption(caption_text, 42)[:4]  # cap 4 lines, never overflow
    if not lines:
        img.save(str(dest), "PNG")
        return dest
    draw = ImageDraw.Draw(img, "RGBA")
    try:
        widths = [draw.textlength(ln, font=font) for ln in lines]
        ascent, descent = font.getmetrics()
        lh = ascent + descent + 8
    except Exception:
        widths = [len(ln) * size * 0.55 for ln in lines]
        lh = size + 10
    max_w = min(max(widths), int(W * max_width_ratio))
    pad_x, pad_y = 24, 14
    box_w = int(max_w + pad_x * 2)
    box_h = int(lh * len(lines) + pad_y * 2)
    margin = int(W * 0.05)
    box_w = min(box_w, W - margin * 2)
    x0 = (W - box_w) // 2
    if position == "center":
        y0 = (H - box_h) // 2
    else:  # lower_third with safe bottom margin
        y0 = int(H * 0.78 - box_h / 2)
        y0 = max(margin, min(y0, H - box_h - margin))
    draw.rounded_rectangle([x0, y0, x0 + box_w, y0 + box_h], radius=18,
                           fill=(0, 0, 0, max(0, min(255, bg_opacity))))
    y = y0 + pad_y
    for ln in lines:
        try:
            lw = draw.textlength(ln, font=font)
        except Exception:
            lw = len(ln) * size * 0.55
        draw.text(((W - min(lw, box_w - pad_x * 2)) / 2, y), ln,
                  font=font, fill=(255, 255, 255, 255))
        y += lh
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(dest), "PNG")
    log("VIDEO", f"Caption overlay -> {dest.name} ({len(lines)} lines, {position})")
    return dest
