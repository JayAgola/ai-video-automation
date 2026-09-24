# Architecture — Parts 1 + 2 + 3 + 4 (P1 dashboard + P2 human review)

## Purpose
Local AI-powered YouTube automation. Pipeline: RESEARCH → TOPIC SELECTION → SCRIPT →
edge-TTS → BGM → mixed audio → visuals → scene chunks → final_video.mp4 → HUMAN REVIEW.

## Layout
- `app/core/` — config/logging/state/cache/project (Part 1, reused; P3 keys added to config).
- `app/llm/`, `app/script/`, `app/audio/` — Part 1, reused.
- `app/visuals/`, `app/video/` — Part 2, reused.
- `app/research/` (NEW, Part 3):
  - `research_provider.py` — Protocol (health + search).
  - `test_provider.py` — deterministic fake data, labelled `TEST DATA — NOT REAL YOUTUBE DATA`.
  - `youtube_provider.py` — YouTube Data API v3 (search + videos stats), quota-aware, error redaction, never scrapes/bypasses.
  - `research_engine.py` — provider select / health / SHA-256 cached search (TTL), bounded retries, `research_engine.index` split.
  - `trend_discovery.py` — normalize + metrics + keyword aggregation.
  - `topic_scorer.py` — deterministic scoring formula, competition, originality_check.
  - `topic_generator.py` — compact LLM summary → llama3.2:3b candidates; deterministic fallback.
  - `seo_engine.py` — titles + scoring + description/tags/keywords/hashtags + thumbnail concepts.
- `pipeline_steps_p3.py` (RESEARCH → TOPIC_DISCOVERY), `pipeline_steps_p3b.py` (TOPIC_RANKING),
  `pipeline_steps_p3c.py` (TOPIC_SELECTED → SEO_GENERATION), `pipeline_steps_p3d.py` (report writer).
- `pipeline_main.py` — added `--research/--query/--top/--select/--force-research/--force-topic/--force-seo/--research-health`;
  manual `--topic` marks research steps skipped.

## State
`FULL_STEPS` = media pipeline only (Part 1+2): SCRIPT,TTS,BGM,MIX,VISUAL_GENERATION,SCENE_CHUNKS,FINAL_VIDEO.
Research steps (RESEARCH,TOPIC_DISCOVERY,TOPIC_RANKING,TOPIC_SELECTED,SEO_GENERATION) live in
`completed_steps` for resume but do NOT gate top-level COMPLETED (manual topic must skip them).

## Research outputs
`projects/<id>/research/{raw/,normalized/,trends.json,topics.json,ranked.json,selected_topic.json,seo.json,research_report.md}`.

## Scoring formula (documented, internal heuristic)
`0.25*trend + 0.20*freshness + 0.20*search_intent + 0.15*engagement + 0.10*content_gap + 0.10*originality − competition/10`.

## Key decisions
- Test research provider is the default (`RESEARCH_PROVIDER=test`, `TEST_RESEARCH_MODE=true`); real
  research needs `YOUTUBE_API_KEY` + `YOUTUBE_RESEARCH_ENABLED=true`. Never fakes real data.
- Research cache key = SHA256(provider+query+region+language+max_results), TTL `RESEARCH_CACHE_TTL_HOURS`.
- Python aggregates/normalizes first; only a compact summary is sent to Ollama (protects context/VRAM).
- No transcript download / no copying competitor content; `originality_check` is a heuristic only.
- API key only in `.env` (git-ignored); exception messages redact credentials.

## Dashboard (Part 4 Prompt 1)
- `app/dashboard/service.py` — pure read-only logic: state loading (safe), pipeline progress over
  `config.DASH_STEPS` (13 steps incl. HUMAN_REVIEW), scene progress (from data.chunks + chunks/ files),
  artifacts map, final_video info (size + duration from state if recorded), log parser (logs/pipeline.log),
  system_status (Ollama reachability only, no model calls).
- `app/dashboard/api.py` — FastAPI `create_app(projects_dir=None)`; routes /api/v1/dashboard/{health,projects,
  projects/{id},projects/{id}/logs,system}; `/` serves `app/dashboard/static/`.
- `app/dashboard/server.py` — `python -m app.dashboard.server` (DASHBOARD_HOST/PORT from .env).
- Frontend: vanilla JS polling (`static/app.js`), index.html + style.css. No auth yet (later prompt).

## YouTube Integration (Part 4 Prompt 3)
- `app/youtube/oauth.py` — Google installed-app OAuth flow (google-auth-oauthlib), scope `youtube.upload`; load/save/refresh tokens to `YOUTUBE_TOKEN_FILE`; safe status query (redacts secrets). Supports test/mock mode.
- `app/youtube/uploader.py` — `upload_video(project_id, client, meta)`: enforces review gate via `is_approved_for_publishing()`, duplicate protection (`status==UPLOADED` → 409), resolves video through ProjectManager, builds metadata via `build_metadata(seo)`, bounded retries on transient failures, writes safe `state.youtube` (status/video_id/url/privacy/title/uploaded_at — never tokens).
- `app/youtube/test_client.py` — mock client labelled `TEST YOUTUBE MODE — NO REAL UPLOAD`; injectable via `get_youtube_client(test=...)`.
- New endpoints: GET `/api/v1/dashboard/youtube/status`, POST `/youtube/connect`, GET `/youtube/callback`, GET `/projects/{id}/youtube/preview`, POST `/projects/{id}/youtube/upload`. Preview/upload both re-validate the review gate server-side (no frontend-only trust).
- Token/credential files git-ignored (`*.json.token`, `credentials.json`, etc.).

## Human Review (Part 4 Prompt 2)
- `app/dashboard/review.py` — review state machine on the existing StateManager:
  NOT_READY (no valid final video, derived) → PENDING (video ready, derived for old projects) →
  APPROVED / REJECTED (explicit human action only) — reset returns APPROVED/REJECTED → PENDING.
  `state.json.review` = {status, reviewer:"local_user", note, created_at, updated_at, history[] (append-only)}.
  `is_approved_for_publishing()` is the future publishing gate. Nothing auto-approves.
- Routes: POST `projects/{id}/review/{approve,reject,reset}`; GET `projects/{id}/video`
  (serves only that project's `output/final_video.mp4`, Range support, 404/traversal-safe).
- UI (app.js): Human Review section (badge, note field, confirm dialogs, history) + Video Review
  `<video>` player; all rendering HTML-escaped via esc().
- Pipeline now documented as: RESEARCH → … → FINAL VIDEO → HUMAN REVIEW → APPROVED → [FUTURE UPLOAD].
  APPROVED is a human-controlled prerequisite, not an upload command.

