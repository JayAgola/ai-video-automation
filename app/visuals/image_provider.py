"""Image provider abstraction. Pipeline talks to providers via this interface only.

generate_image(prompt, output_path, width, height, settings) -> dict metadata
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class ImageProvider(Protocol):
    name: str

    def health(self) -> dict[str, Any]:
        ...

    def generate_image(self, prompt: str, output_path: Path | str,
                       width: int, height: int,
                       settings: dict[str, Any] | None = None) -> dict[str, Any]:
        ...


class StockProvider(Protocol):
    """Licensed stock source (Part 2.2). Same architecture as ImageProvider.

    A stock source is searched first (`search`) and only then downloaded
    (`fetch`), so candidate scoring can reject bad/duplicate assets before any
    bytes are transferred. Providers are cached + deterministic; secrets are
    never logged.
    """
    name: str              # "pexels" | "pixabay" | "local" | "mock"
    kind: str              # always "stock"

    def health(self) -> dict[str, Any]:
        ...

    def search(self, query: str, media_type: str = "photo", count: int = 10,
               width: int = 1280, height: int = 720,
               settings: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        ...

    def fetch(self, candidate: dict[str, Any], output_path: Path | str,
              width: int, height: int,
              settings: dict[str, Any] | None = None) -> dict[str, Any]:
        ...
