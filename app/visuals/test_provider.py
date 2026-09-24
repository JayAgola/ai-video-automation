"""Deterministic TEST placeholder provider (clearly NOT production visuals).

Represents a CLEAN visual with no captions: deterministic gradient scene +
small corner tag only (scene id), never the narration/caption text.
Used for TEST_VISUAL_MODE only.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.logger import log


class TestImageProvider:
    name = "test"

    def health(self) -> dict[str, Any]:
        return {"ok": True, "provider": "test", "status": "AVAILABLE",
                "note": "Deterministic placeholder images for testing only."}

    def generate_image(self, prompt: str, output_path: Path | str,
                       width: int, height: int,
                       settings: dict[str, Any] | None = None) -> dict[str, Any]:
        from PIL import Image, ImageDraw, ImageFont  # Pillow (already via moviepy dep chain)
        settings = settings or {}
        scene_id = str(settings.get("scene_id", ""))
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        # Deterministic clean "scene": gradient sky + sun + mountains, no text.
        seed = int(settings.get("seed", 12345))
        img = Image.new("RGB", (width, height))
        px = img.load()
        top = ((seed * 37) % 90 + 20, (seed * 91) % 90 + 40, (seed * 53) % 80 + 120)
        bottom = (244, 214, 170)
        for y in range(height):
            t = y / max(height - 1, 1)
            px_col = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
            for x in range(width):
                px[x, y] = px_col
        d = ImageDraw.Draw(img, "RGBA")
        # Sun (position varies deterministically with seed).
        sx = int(width * (0.25 + (seed % 50) / 100.0))
        sy = int(height * 0.32)
        sr = int(min(width, height) * 0.09)
        d.ellipse([sx - sr, sy - sr, sx + sr, sy + sr], fill=(255, 236, 180, 255))
        # Mountain silhouettes (clean geometry, no letters).
        d.polygon([(0, height), (int(width * 0.28), int(height * 0.52)),
                   (int(width * 0.55), height)], fill=(60, 70, 90, 255))
        d.polygon([(int(width * 0.35), height), (int(width * 0.68), int(height * 0.45)),
                   (width, height)], fill=(40, 48, 66, 255))
        # Small corner tag = scene id only (debug aid, never narration/caption).
        try:
            font = ImageFont.load_default()
        except Exception:
            font = None
        tag = f"scene {scene_id}".strip() or "clean visual"
        d.rectangle([8, 8, 150, 34], fill=(0, 0, 0, 110))
        d.text((14, 13), tag, fill=(255, 255, 255), font=font)
        img.save(str(out), "PNG")
        log("VISUAL", f"Test clean visual -> {out.name}")
        return {"provider": "test", "path": str(out), "width": width,
                "height": height, "seed": seed, "test_mode": True}
