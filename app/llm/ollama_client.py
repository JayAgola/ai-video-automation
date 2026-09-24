"""Single centralized Ollama client. Rest of app must NOT call Ollama directly."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from app.core import config
from app.core.logger import log


@dataclass
class OllamaResult:
    ok: bool
    text: str = ""
    error: str = ""
    model: str = ""
    raw: dict | None = None


def model_in_list(name: str, models: list[str]) -> bool:
    """True when `name` matches an installed Ollama model tag.

    Single place for the "base name vs tag" rule (e.g. 'llama3.2' matches
    'llama3.2:3b') used by both the health check and the SCRIPT model resolver.
    """
    want = str(name or "").strip()
    if not want:
        return False
    return any(m == want or m.startswith(want + ":") or want.startswith(m)
               for m in (models or []))


class OllamaClient:
    def __init__(self, base_url: str | None = None, text_model: str | None = None,
                 reasoning_model: str | None = None, timeout: int | None = None):
        self.base_url = (base_url or config.OLLAMA_BASE_URL).rstrip("/")
        self.text_model = text_model or config.OLLAMA_TEXT_MODEL
        self.reasoning_model = reasoning_model or config.OLLAMA_REASONING_MODEL
        self.timeout = config.OLLAMA_TIMEOUT if timeout is None else timeout

    # ---- health ----
    def check_connection(self) -> dict[str, Any]:
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=10)
            if r.status_code == 200:
                log("OLLAMA", "Connected")
                return {"ok": True, "status": "ONLINE"}
            return {"ok": False, "status": "OFFLINE", "error": f"HTTP {r.status_code}"}
        except Exception as e:  # never crash app
            return {"ok": False, "status": "OFFLINE", "error": f"{type(e).__name__}: {e}"}

    def check_model(self, model_name: str | None = None) -> dict[str, Any]:
        model = model_name or self.text_model
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=10)
            r.raise_for_status()
            models = [m.get("name", "") for m in r.json().get("models", [])]
            if model_in_list(model, models):
                log("OLLAMA", f"Model AVAILABLE: {model}")
                return {"ok": True, "model": model, "status": "AVAILABLE", "models": models}
            return {"ok": False, "model": model, "status": "MISSING",
                    "error": f"Model '{model}' not installed. Available: {models}"}
        except Exception as e:
            return {"ok": False, "model": model, "status": "UNKNOWN", "error": f"{type(e).__name__}: {e}"}

    # ---- generation ----
    def generate(self, prompt: str, model: str | None = None,
                 system: str | None = None, options: dict | None = None,
                 fmt: str | None = None) -> OllamaResult:
        """One-shot generation.

        fmt: optional Ollama structured-output mode (e.g. "json"). Purely
        additive — omitted callers keep the previous behavior.
        """
        model = model or self.text_model
        payload: dict[str, Any] = {"model": model, "prompt": prompt, "stream": False}
        if system:
            payload["system"] = system
        if options:
            payload["options"] = options
        if fmt:
            payload["format"] = fmt
        try:
            r = requests.post(f"{self.base_url}/api/generate", json=payload, timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
            return OllamaResult(ok=True, text=data.get("response", ""), model=model, raw=data)
        except Exception as e:
            return OllamaResult(ok=False, error=f"{type(e).__name__}: {e}", model=model)

    def generate_reasoning(self, prompt: str, system: str | None = None) -> OllamaResult:
        return self.generate(prompt, model=self.reasoning_model, system=system)
