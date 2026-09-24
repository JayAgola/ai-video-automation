"""Centralized configuration. Values from .env override defaults. No hard-coded machine paths."""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent.parent.parent

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_TEXT_MODEL = os.getenv("OLLAMA_TEXT_MODEL", "llama3.2:3b")
OLLAMA_REASONING_MODEL = os.getenv("OLLAMA_REASONING_MODEL", "deepseek-r1:7b")
# Single place for the Ollama HTTP timeout (seconds). deepseek-r1:7b thinks
# much longer than llama3.2:3b on laptop GPUs; a 300s default times out
# mid-script. Configurable via OLLAMA_TIMEOUT (also in .env.example).
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "900"))

TTS_VOICE = os.getenv("TTS_VOICE", "en-US-ChristopherNeural")
BGM_VOLUME = float(os.getenv("BGM_VOLUME", "0.10"))

PROJECTS_DIR = Path(os.getenv("PROJECTS_DIR", str(ROOT_DIR / "projects")))
CACHE_DIR = Path(os.getenv("CACHE_DIR", str(ROOT_DIR / "cache")))
ASSETS_DIR = Path(os.getenv("ASSETS_DIR", str(ROOT_DIR / "assets")))
BGM_DIR = ASSETS_DIR / "bgm"

# Pipeline step order for Part 1 (extensible for Part 2).
PART1_STEPS = ["SCRIPT", "TTS", "BGM", "MIX"]

# Full pipeline steps (Part 1 + Part 2). State completion is judged on these.
FULL_STEPS = ["SCRIPT", "TTS", "BGM", "MIX", "VISUAL_GENERATION", "SCENE_CHUNKS", "FINAL_VIDEO"]

# Full pipeline steps including Part 3 research/SEO (manual --topic may skip these).
P3_STEPS = ["RESEARCH", "TOPIC_DISCOVERY", "TOPIC_RANKING", "TOPIC_SELECTED", "SEO_GENERATION"]
FULL_STEPS_P3 = P3_STEPS + FULL_STEPS

# ---- Part 3: research / niche ----
CHANNEL_NICHE = os.getenv("CHANNEL_NICHE", "Modern Stoicism and Applied Psychology")
CHANNEL_LANGUAGE = os.getenv("CHANNEL_LANGUAGE", "en")
TARGET_COUNTRY = os.getenv("TARGET_COUNTRY", "US")
RESEARCH_REGION = os.getenv("RESEARCH_REGION", os.getenv("TARGET_COUNTRY", "US"))
TARGET_AUDIENCE = os.getenv("TARGET_AUDIENCE", "Adults interested in self improvement")

RESEARCH_PROVIDER = os.getenv("RESEARCH_PROVIDER", "test")  # test | youtube
TEST_RESEARCH_MODE = os.getenv("TEST_RESEARCH_MODE", "true").lower() in ("1", "true", "yes")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
YOUTUBE_RESEARCH_ENABLED = os.getenv("YOUTUBE_RESEARCH_ENABLED", "false").lower() in ("1", "true", "yes")
RESEARCH_CACHE_TTL_HOURS = float(os.getenv("RESEARCH_CACHE_TTL_HOURS", "24"))
YOUTUBE_MAX_RESULTS = int(os.getenv("YOUTUBE_MAX_RESULTS", "25"))
YOUTUBE_MAX_QUERIES_PER_RUN = int(os.getenv("YOUTUBE_MAX_QUERIES_PER_RUN", "10"))
TOPIC_COUNT = int(os.getenv("TOPIC_COUNT", "12"))
_default_queries = ("stoicism anxiety,stoicism overthinking,psychology overthinking,"
    "emotional control psychology,discipline psychology,people pleasing psychology,"
    "confidence psychology,procrastination psychology")
RESEARCH_QUERIES = [q.strip() for q in os.getenv("RESEARCH_QUERIES", _default_queries).split(",") if q.strip()]


VISUAL_PROVIDER = os.getenv("VISUAL_PROVIDER", "test")  # test | comfyui
TEST_VISUAL_MODE = os.getenv("TEST_VISUAL_MODE", "false").lower() in ("1", "true", "yes")
COMFYUI_BASE_URL = os.getenv("COMFYUI_BASE_URL", "http://127.0.0.1:8188")
COMFYUI_MODEL = os.getenv("COMFYUI_MODEL", "sd_xl_base_1.0.safetensors")
VISUAL_SEED = int(os.getenv("VISUAL_SEED", "12345"))

# ---- Visual text-separation (Part 2 fix): clean AI image, captions in renderer ----
# Bump to invalidate image caches that embedded narration/caption text.
VISUAL_CACHE_VERSION = os.getenv("VISUAL_CACHE_VERSION", "v2_no_text")
# Global negative prompt: no text/typography ever in generated images.
VISUAL_NEGATIVE_PROMPT = os.getenv(
    "VISUAL_NEGATIVE_PROMPT",
    "no text, no words, no letters, no numbers, no typography, no captions, "
    "no subtitles, no quotes, no writing, no logos, no watermarks, no sign text, "
    "no labels, no speech bubbles, no UI text, blurry, watermark",
)
# Caption overlay (renderer stage only — never sent to image generator).
CAPTION_ENABLED = os.getenv("CAPTION_ENABLED", "true").lower() in ("1", "true", "yes")
CAPTION_POSITION = os.getenv("CAPTION_POSITION", "lower_third")  # lower_third | center
CAPTION_FONT_SIZE = int(os.getenv("CAPTION_FONT_SIZE", "48"))
CAPTION_MAX_WIDTH_RATIO = float(os.getenv("CAPTION_MAX_WIDTH_RATIO", "0.86"))
CAPTION_BG_OPACITY = int(os.getenv("CAPTION_BG_OPACITY", "160"))  # 0-255
CAPTION_VERSION = os.getenv("CAPTION_VERSION", "v1")

# ---- Script generation robustness (Part 2.1): small-model JSON repair ----
# Deterministic narration->duration fallback when LLM omits/invalidates it.
# Reuses TTS speech rate (~2.5 words/sec for edge-tts) rather than a 2nd system.
SCRIPT_WPS = float(os.getenv("SCRIPT_WPS", "2.5"))  # words per second of narration
SCENE_MIN_SECONDS = float(os.getenv("SCENE_MIN_SECONDS", "5"))
SCENE_MAX_SECONDS = float(os.getenv("SCENE_MAX_SECONDS", "30"))
# Part 2.1+.2 script-duration target for long-form (3-4 min) YouTube videos.
# Per-scene clamp stays SCENE_MIN/MAX_SECONDS; this gate validates total + count.
SCRIPT_TARGET_MIN_SECONDS = float(os.getenv("SCRIPT_TARGET_MIN_SECONDS", "180"))
SCRIPT_TARGET_MAX_SECONDS = float(os.getenv("SCRIPT_TARGET_MAX_SECONDS", "240"))
SCRIPT_MIN_SCENES = int(os.getenv("SCRIPT_MIN_SCENES", "8"))
SCRIPT_MAX_SCENES = int(os.getenv("SCRIPT_MAX_SCENES", "16"))
# Bounded extra LLM attempts used ONLY to expand a too-short script with real
# narration (never stretching/duplicating downstream audio).
SCRIPT_EXPAND_RETRIES = int(os.getenv("SCRIPT_EXPAND_RETRIES", "2"))
# Small local models (llama3.2:3b) truncate long JSON at Ollama's default
# context window, producing "Expecting ',' delimiter" at a fixed offset.
# Raise context + output cap explicitly for script generation.
SCRIPT_NUM_CTX = int(os.getenv("SCRIPT_NUM_CTX", "8192"))
SCRIPT_MAX_TOKENS = int(os.getenv("SCRIPT_MAX_TOKENS", "4096"))

# ---- Script model + long-form prompt budget (script reliability) ----
# Dedicated model for SCRIPT generation. If the preferred model is not installed,
# generation falls back to OLLAMA_TEXT_MODEL (availability is checked through the
# existing centralized Ollama client — never hardcoded in the script engine).
# Keep the default (llama3.2:3b): a non-thinking model follows Ollama's JSON mode,
# which is what makes a long structured reply reliable. Reasoning builds cannot:
# deepseek-r1:7b answers with an EMPTY "{}" under "format": "json" (measured
# 2026-09-22: 6 chars in ~24s), which used to fail SCRIPT with "scenes must be a
# non-empty list". script_engine.json_mode_supported() now calls such models in
# PLAIN mode (their <think> trace / surrounding prose is handled by the parser),
# but they are much slower and can truncate at SCRIPT_MAX_TOKENS.
SCRIPT_MODEL = os.getenv("SCRIPT_MODEL", "llama3.2:3b")
# Ask Ollama for constrained JSON output ("format": "json") on script calls, so a
# small model cannot wrap the script in prose or ``` fences. Set to false if your
# model/server build mishandles structured output.
SCRIPT_JSON_MODE = os.getenv("SCRIPT_JSON_MODE", "true").lower() in ("1", "true", "yes")
# Spoken-narration budget per scene. Used ONLY to translate "15-25 seconds" into a
# word count the model can actually follow (words = seconds * SCRIPT_WPS).
# Duration estimation itself still uses real narration word counts.
SCRIPT_NARRATION_MIN_SECONDS = float(os.getenv("SCRIPT_NARRATION_MIN_SECONDS", "15"))
SCRIPT_NARRATION_MAX_SECONDS = float(os.getenv("SCRIPT_NARRATION_MAX_SECONDS", "25"))

# ---- Part 2.2: hybrid visual sources (stock photo/video, local assets, AI) ----
# AI is NOT forced for every scene: real-world subjects (people/animals/places)
# prefer licensed stock, because AI anatomy is frequently malformed.
VISUAL_SOURCE_MODE = os.getenv("VISUAL_SOURCE_MODE", "auto")  # auto | ai | stock | local
# API keys: from env/.env only. NEVER logged and NEVER exposed in as_dict().
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "")
# Bounded, deterministic stock search + quality filters (16:9 friendly).
STOCK_MAX_RESULTS = int(os.getenv("STOCK_MAX_RESULTS", "10"))
STOCK_MIN_WIDTH = int(os.getenv("STOCK_MIN_WIDTH", "1280"))
STOCK_MIN_HEIGHT = int(os.getenv("STOCK_MIN_HEIGHT", "720"))
STOCK_TIMEOUT = int(os.getenv("STOCK_TIMEOUT", "30"))
STOCK_MAX_RETRIES = int(os.getenv("STOCK_MAX_RETRIES", "2"))
STOCK_SAFESEARCH = os.getenv("STOCK_SAFESEARCH", "true").lower() in ("1", "true", "yes")
STOCK_ALLOW_VIDEO = os.getenv("STOCK_ALLOW_VIDEO", "true").lower() in ("1", "true", "yes")
STOCK_MIN_VIDEO_SECONDS = float(os.getenv("STOCK_MIN_VIDEO_SECONDS", "3"))
# Search-result TTL: providers require caching + we must avoid duplicate API calls.
STOCK_CACHE_TTL_HOURS = float(os.getenv("STOCK_CACHE_TTL_HOURS", "168"))
STOCK_CACHE_VERSION = os.getenv("STOCK_CACHE_VERSION", "v1_hybrid")
# Local asset lookup (reuses existing assets/ + projects/<id>/assets/, no new layout).
LOCAL_STOCK_DIRNAME = os.getenv("LOCAL_STOCK_DIRNAME", "stock")
STOCK_VIDEO_MAX_BYTES = int(os.getenv("STOCK_VIDEO_MAX_BYTES", "26214400"))
# "photo" (default, cheapest+deterministic) | "video" | "any"
STOCK_MEDIA_PREFERENCE = os.getenv("STOCK_MEDIA_PREFERENCE", "photo")
# Deterministic offline stock providers for tests (no network, no API keys).
STOCK_MOCK_MODE = os.getenv("STOCK_MOCK_MODE", "false").lower() in ("1", "true", "yes")

# ---- Part 4 Prompt 1: dashboard / logs ----
LOGS_DIR = Path(os.getenv("LOGS_DIR", str(ROOT_DIR / "logs")))
LOG_FILE = LOGS_DIR / "pipeline.log"
DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "127.0.0.1")
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8000"))
DASHBOARD_STATIC_DIR = ROOT_DIR / "app" / "dashboard" / "static"

# ---- Part 4 Prompt 3: YouTube OAuth + upload ----
YOUTUBE_UPLOAD_ENABLED = os.getenv("YOUTUBE_UPLOAD_ENABLED", "false").lower() in ("1", "true", "yes")
TEST_YOUTUBE_MODE = os.getenv("TEST_YOUTUBE_MODE", "false").lower() in ("1", "true", "yes")
YOUTUBE_CLIENT_SECRET_FILE = Path(os.getenv(
    "YOUTUBE_CLIENT_SECRET_FILE", str(ROOT_DIR / "credentials" / "client_secret.json")))
YOUTUBE_TOKEN_FILE = Path(os.getenv(
    "YOUTUBE_TOKEN_FILE", str(ROOT_DIR / "credentials" / "youtube_token.json")))
YOUTUBE_DEFAULT_PRIVACY = os.getenv("YOUTUBE_DEFAULT_PRIVACY", "private").lower()
YOUTUBE_OAUTH_PORT = int(os.getenv("YOUTUBE_OAUTH_PORT", "8090"))
YOUTUBE_OAUTH_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
# Display order for the dashboard pipeline panel (research + media + review).
DASH_STEPS = ["RESEARCH", "TOPIC_DISCOVERY", "TOPIC_RANKING", "TOPIC_SELECTED",
              "SEO_GENERATION", "SCRIPT", "TTS", "BGM", "MIX", "VISUAL_GENERATION",
              "SCENE_CHUNKS", "FINAL_VIDEO", "HUMAN_REVIEW"]

IMAGE_WIDTH = int(os.getenv("IMAGE_WIDTH", "1280"))
IMAGE_HEIGHT = int(os.getenv("IMAGE_HEIGHT", "720"))

VIDEO_FPS = int(os.getenv("VIDEO_FPS", "30"))
VIDEO_WIDTH = int(os.getenv("VIDEO_WIDTH", "1920"))
VIDEO_HEIGHT = int(os.getenv("VIDEO_HEIGHT", "1080"))
VIDEO_CRF = int(os.getenv("VIDEO_CRF", "20"))
VIDEO_PRESET = os.getenv("VIDEO_PRESET", "medium")

FUTURE_STEPS = [
    "RESEARCH", "TOPIC", "SCRIPT", "TTS", "VISUAL_GENERATION",
    "SCENE_CHUNKS", "BGM", "FINAL_VIDEO", "SEO", "HUMAN_REVIEW", "YOUTUBE",
]


def ensure_dirs() -> None:
    for d in [
        PROJECTS_DIR,
        CACHE_DIR, CACHE_DIR / "audio", CACHE_DIR / "images",
        CACHE_DIR / "chunks", CACHE_DIR / "research", CACHE_DIR / "stock",
        ASSETS_DIR, BGM_DIR,
    ]:
        d.mkdir(parents=True, exist_ok=True)


def as_dict() -> dict:
    return {
        "OLLAMA_BASE_URL": OLLAMA_BASE_URL,
        "OLLAMA_TEXT_MODEL": OLLAMA_TEXT_MODEL,
        "OLLAMA_REASONING_MODEL": OLLAMA_REASONING_MODEL,
        "TTS_VOICE": TTS_VOICE,
        "BGM_VOLUME": BGM_VOLUME,
        "PROJECTS_DIR": str(PROJECTS_DIR),
        "CACHE_DIR": str(CACHE_DIR),
        "ASSETS_DIR": str(ASSETS_DIR),
        "VISUAL_PROVIDER": VISUAL_PROVIDER,
        "TEST_VISUAL_MODE": TEST_VISUAL_MODE,
        "COMFYUI_BASE_URL": COMFYUI_BASE_URL,
        "COMFYUI_MODEL": COMFYUI_MODEL,
        "VISUAL_SEED": VISUAL_SEED,
        "VISUAL_CACHE_VERSION": VISUAL_CACHE_VERSION,
        "VISUAL_NEGATIVE_PROMPT": VISUAL_NEGATIVE_PROMPT,
        "CAPTION_ENABLED": CAPTION_ENABLED,
        "CAPTION_POSITION": CAPTION_POSITION,
        "CAPTION_FONT_SIZE": CAPTION_FONT_SIZE,
        "CAPTION_MAX_WIDTH_RATIO": CAPTION_MAX_WIDTH_RATIO,
        "CAPTION_BG_OPACITY": CAPTION_BG_OPACITY,
        "CAPTION_VERSION": CAPTION_VERSION,
        "SCRIPT_WPS": SCRIPT_WPS,
        "SCENE_MIN_SECONDS": SCENE_MIN_SECONDS,
        "SCENE_MAX_SECONDS": SCENE_MAX_SECONDS,
        "SCRIPT_TARGET_MIN_SECONDS": SCRIPT_TARGET_MIN_SECONDS,
        "SCRIPT_TARGET_MAX_SECONDS": SCRIPT_TARGET_MAX_SECONDS,
        "SCRIPT_MIN_SCENES": SCRIPT_MIN_SCENES,
        "SCRIPT_MAX_SCENES": SCRIPT_MAX_SCENES,
        "SCRIPT_EXPAND_RETRIES": SCRIPT_EXPAND_RETRIES,
        "SCRIPT_NUM_CTX": SCRIPT_NUM_CTX,
        "SCRIPT_MAX_TOKENS": SCRIPT_MAX_TOKENS,
        "SCRIPT_MODEL": SCRIPT_MODEL,
        "SCRIPT_JSON_MODE": SCRIPT_JSON_MODE,
        "SCRIPT_NARRATION_MIN_SECONDS": SCRIPT_NARRATION_MIN_SECONDS,
        "SCRIPT_NARRATION_MAX_SECONDS": SCRIPT_NARRATION_MAX_SECONDS,
        "OLLAMA_TIMEOUT": OLLAMA_TIMEOUT,
        # Part 2.2 hybrid visual sources (secrets intentionally excluded).
        "VISUAL_SOURCE_MODE": VISUAL_SOURCE_MODE,
        "PEXELS_API_KEY_SET": bool(PEXELS_API_KEY),
        "PIXABAY_API_KEY_SET": bool(PIXABAY_API_KEY),
        "STOCK_MAX_RESULTS": STOCK_MAX_RESULTS,
        "STOCK_MIN_WIDTH": STOCK_MIN_WIDTH,
        "STOCK_MIN_HEIGHT": STOCK_MIN_HEIGHT,
        "STOCK_TIMEOUT": STOCK_TIMEOUT,
        "STOCK_MAX_RETRIES": STOCK_MAX_RETRIES,
        "STOCK_SAFESEARCH": STOCK_SAFESEARCH,
        "STOCK_ALLOW_VIDEO": STOCK_ALLOW_VIDEO,
        "STOCK_CACHE_TTL_HOURS": STOCK_CACHE_TTL_HOURS,
        "STOCK_CACHE_VERSION": STOCK_CACHE_VERSION,
        "IMAGE_WIDTH": IMAGE_WIDTH,
        "IMAGE_HEIGHT": IMAGE_HEIGHT,
        "VIDEO_FPS": VIDEO_FPS,
        "VIDEO_WIDTH": VIDEO_WIDTH,
        "VIDEO_HEIGHT": VIDEO_HEIGHT,
        "VIDEO_CRF": VIDEO_CRF,
        "VIDEO_PRESET": VIDEO_PRESET,
        "CHANNEL_NICHE": CHANNEL_NICHE,
        "CHANNEL_LANGUAGE": CHANNEL_LANGUAGE,
        "TARGET_COUNTRY": TARGET_COUNTRY,
        "RESEARCH_REGION": RESEARCH_REGION,
        "TARGET_AUDIENCE": TARGET_AUDIENCE,
        "RESEARCH_PROVIDER": RESEARCH_PROVIDER,
        "TEST_RESEARCH_MODE": TEST_RESEARCH_MODE,
        "YOUTUBE_RESEARCH_ENABLED": YOUTUBE_RESEARCH_ENABLED,
        "RESEARCH_CACHE_TTL_HOURS": RESEARCH_CACHE_TTL_HOURS,
        "YOUTUBE_MAX_RESULTS": YOUTUBE_MAX_RESULTS,
        "YOUTUBE_MAX_QUERIES_PER_RUN": YOUTUBE_MAX_QUERIES_PER_RUN,
        "TOPIC_COUNT": TOPIC_COUNT,
        "LOGS_DIR": str(LOGS_DIR),
        "DASHBOARD_HOST": DASHBOARD_HOST,
        "DASHBOARD_PORT": DASHBOARD_PORT,
        "YOUTUBE_UPLOAD_ENABLED": YOUTUBE_UPLOAD_ENABLED,
        "TEST_YOUTUBE_MODE": TEST_YOUTUBE_MODE,
        "YOUTUBE_DEFAULT_PRIVACY": YOUTUBE_DEFAULT_PRIVACY,
    }
