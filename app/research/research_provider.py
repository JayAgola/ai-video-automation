"""Research provider abstraction (mirrors app/visuals provider pattern).

Providers implement: name, health(), search(query, ...) -> list[dict raw].
Pipeline code must use get_research_provider(), never import a provider directly.
"""
from __future__ import annotations

from typing import Any, Protocol


class ResearchProvider(Protocol):
    name: str

    def health(self) -> dict[str, Any]:
        ...

    def search(self, query: str, max_results: int = 25, region: str = "US",
               language: str = "en") -> list[dict[str, Any]]:
        ...
