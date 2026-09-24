# Known issues
- Part 2.2 stock: NO real Pexels/Pixabay API call was made (no keys configured in this
  environment) — providers verified via offline mocks + HTTP-shape unit tests (safesearch,
  orientation, header-only Pexels key, redaction). First real run may surface API quirks.
- Part 2.2 stock: only PHOTOS are auto-selected; stock VIDEO is opt-in per scene via
  `stock_media: "video"` (gated by `STOCK_ALLOW_VIDEO`) to keep downloads small/cheap.
- Part 2.2 stock: Pixabay requires the API key as a URL query parameter (provider rule);
  error paths redact it and URLs are never logged, but it cannot be moved to a header.
- Part 2.2 stock: AUTO scene text "unknown" falls back to stock-first (real-world prior);
  scenes with poor LLM planning fields may search with a weak query derived from the
  visual description (stock_search_query fallback).
- TTS needs internet (edge-tts cloud API).
- NVENC unusable on this machine (driver API 12.2 < 13.1) -> libx264 CPU fallback.
- ComfyUI not installed/running -> real-art path unverified end-to-end (negative prompt + visual-only prompts verified via unit path + workflow payload only).
- assets/bgm has a synthetic tone (test) and a mixed MP3; keep only licensed files.
- YouTube research provider implemented but NOT integration-tested live (no API key set here);
  health path + failure handling verified via DISABLED/NO_API_KEY and unblocked via TTL cache.
- OCR text-in-image check skipped (pytesseract/tesseract not installed); separation enforced at prompt/cache/renderer level + focused unit tests instead.
- Legacy projects (e.g. video_001 script.json) still contain `Text: '...'` in `visual_direction`; fixed pipeline sanitizes at build time + v2 cache key forces regeneration, but old PNGs on disk remain until rebuilt with --fresh/--force-visuals.
- Research topic candidates depend on llama3.2:3b quality; deterministic fallback is more formulaic.
- llama3.2:3b JSON reliability: it frequently omits the final `]`/`}` (fixed structurally by
  `parse_script_json`) and may close an object with `}` inside the `scenes` array; such defects
  still consume a retry (now with an actionable JSON correction). A larger model or Ollama
  structured outputs (`format: json`) would reduce retries but were not adopted here.
- SEO title "Why <keyword>" lowercases a name keyword (cosmetic; scoring still picks natural full titles).
- Research cache is global (no per-channel isolation); key includes query+region+language+max but not provider match count beyond these.
- Reviewer is `local_user` constant — no auth yet (later Part 4 prompt).
- Dashboard log viewer requires the logger's file output (logs/pipeline.log); older log lines pre-dating a project won't appear.
- Video playback route supports simple Range serving; untested against very large (>1GB) files.
- Dashboard auto-refresh is manual polling only (no auto interval yet).
- YouTube OAuth + upload use a mock client in tests (TEST_YOUTUBE_MODE=true); real OAuth flow not exercised end-to-end here.
- OAuth token file is local-only; no encryption at rest (local single-user app; documented limitation).
- YouTube quota/metadata validation edge cases (e.g., >100 tags, extremely long descriptions) not exhaustively tested against the live API.


