"""Targeted Part 1 validation (run individually, not all at once)."""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_ollama() -> bool:
    from app.llm.ollama_client import OllamaClient
    c = OllamaClient()
    conn = c.check_connection()
    print("connection:", conn)
    if not conn["ok"]:
        print("OLLAMA TEST: FAIL (offline, is `ollama serve` running?)")
        return False
    chk = c.check_model()
    print("model:", chk.get("model"), chk.get("status"))
    if not chk["ok"]:
        print("OLLAMA TEST: FAIL (model missing)")
        return False
    r = c.generate("Reply with exactly: OK")
    ok = r.ok and "OK" in r.text.upper()
    print("generate:", r.text[:120], "->", "PASS" if ok else "FAIL")
    return ok
