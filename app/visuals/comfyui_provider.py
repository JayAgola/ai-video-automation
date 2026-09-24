"""ComfyUI provider stub: interface + health check + real generation path.

Does NOT download ComfyUI or models. If ComfyUI is not reachable, health()
reports it and generate_image() raises a clear error (never fakes an image).
One job at a time (sequential) to respect RTX 3050 VRAM.
"""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path
from typing import Any

from app.core.logger import log


class ComfyUIProvider:
    name = "comfyui"

    def __init__(self, base_url: str, model: str = ""):
        self.base_url = base_url.rstrip("/")
        self.model = model

    def health(self) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(f"{self.base_url}/system_stats", timeout=8) as r:
                ok = r.status == 200
            return {"ok": ok, "provider": "comfyui", "base_url": self.base_url,
                    "status": "AVAILABLE" if ok else "UNREACHABLE"}
        except Exception as e:
            return {"ok": False, "provider": "comfyui", "base_url": self.base_url,
                    "status": "UNREACHABLE",
                    "error": f"{type(e).__name__}: {e}. Start ComfyUI or use TEST_VISUAL_MODE=true."}

    def _default_workflow(
        self,
        prompt: str,
        width: int,
        height: int,
        seed: int,
        filename_prefix: str = "YT001",
        negative_prompt: str | None = None,
    ) -> dict:
        from app.core import config as _cfg
        negative_prompt = negative_prompt or _cfg.VISUAL_NEGATIVE_PROMPT
        return {
            "3": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": seed,
                    "steps": 20,
                    "cfg": 7.0,
                    "sampler_name": "euler",
                    "scheduler": "normal",
                    "denoise": 1.0,
                    "model": ["4", 0],
                    "positive": ["6", 0],
                    "negative": ["7", 0],
                    "latent_image": ["5", 0]
                }
            },

            "4": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {
                    "ckpt_name": self.model
                }
            },

            "5": {
                "class_type": "EmptyLatentImage",
                "inputs": {
                    "width": width,
                    "height": height,
                    "batch_size": 1
                }
            },

            "6": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "text": prompt,
                    "clip": ["4", 1]
                }
            },

            "7": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "text": negative_prompt,
                    "clip": ["4", 1]
                }
            },

            "8": {
                "class_type": "VAEDecode",
                "inputs": {
                    "samples": ["3", 0],
                    "vae": ["4", 2]
                }
            },

            "9": {
                "class_type": "SaveImage",
                "inputs": {
                    "images": ["8", 0],
                    "filename_prefix": filename_prefix
                }
            }
        }

    def generate_image(self, prompt: str, output_path: Path | str,
                       width: int, height: int,
                       settings: dict[str, Any] | None = None) -> dict[str, Any]:
        settings = settings or {}
        seed = int(settings.get("seed", 12345))
        filename_prefix = (f"{settings.get('project_id', 'project')}_"f"scene_{settings.get('scene_id', '000')}")
        workflow = settings.get("workflow") or self._default_workflow(
            prompt, width, height, seed, filename_prefix,
            settings.get("negative_prompt"))
        payload = json.dumps({"prompt": workflow}).encode()
        req = urllib.request.Request(f"{self.base_url}/prompt", data=payload,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode())
            prompt_id = data["prompt_id"]
        except Exception as e:
            raise RuntimeError(
                f"ComfyUI not reachable at {self.base_url}: {type(e).__name__}: {e}. "
                "Start ComfyUI or set TEST_VISUAL_MODE=true for placeholder mode.") from e
        # Poll history (sequential, one job) until done.
        for _ in range(600):  # ~20 min cap
            time.sleep(2)
            try:
                with urllib.request.urlopen(
                        f"{self.base_url}/history/{prompt_id}", timeout=15) as r:
                    hist = json.loads(r.read().decode())
                if prompt_id in hist:
                    outs = hist[prompt_id].get("outputs", {})
                    for node_out in outs.values():
                        for img in node_out.get("images", []):
                            fn = img["filename"]
                            url = (f"{self.base_url}/view?filename={fn}"
                                   f"&subfolder={img.get('subfolder', '')}&type=output")
                            out = Path(output_path)
                            out.parent.mkdir(parents=True, exist_ok=True)
                            urllib.request.urlretrieve(url, str(out))
                            log("VISUAL", f"ComfyUI image -> {out.name}")
                            return {"provider": "comfyui", "model": self.model,
                                    "path": str(out), "width": width,
                                    "height": height, "seed": seed}
            except RuntimeError:
                raise
            except Exception:
                continue
        raise TimeoutError("ComfyUI generation timed out.")
