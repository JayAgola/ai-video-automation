# Completed tasks (Part 2.1 — robust script generation, 2026-09-19)
- Root cause: llama3.2:3b stops after the last scene object and omits the final `]`/`}` -> `json.loads` raised "Expecting ',' delimiter" at the end of the text, so SCRIPT failed all 3 attempts on `video_003`.
- `app/script/script_engine.py`: new `parse_script_json()` (valid JSON first -> `_close_containers()` structural salvage -> drop trailing half-written scene via `_scene_complete()`; never invents content) now used by both the existing Ollama call sites; script prompt hardened (no unescaped quotes, valid JSON, no extra fields); retry correction is compact + explicit for JSON syntax vs schema errors (was empty for JSON errors).
- `app/core/config.py`: `SCRIPT_NUM_CTX` (8192) / `SCRIPT_MAX_TOKENS` (4096) + `config_snapshot()` entries. Missing-duration derivation (`estimate_duration` + clamp to `SCENE_MIN_SECONDS`/`SCENE_MAX_SECONDS`) and empty-narration fatal check stay in `pre_validate_script` (pre-Pydantic, no retry burn); empty narration is NEVER replaced with prompt/caption/topic text.
- `pipeline_main.py`: `script_is_resumable()` — `--resume` now retries SCRIPT when it is in `failed_steps` (previously "resume requested but SCRIPT not completed" dead-ended every project that failed at SCRIPT).
- `tests/test_script_robust.py`: T1-T20 (missing duration derived+clamped, valid duration preserved, extreme duration clamped, empty/whitespace narration fatal + Pydantic rejection, `Text: '...'` sanitized, narration/caption never in visual prompt, legacy + unchanged scripts, correction messages, no error dumps, resume gates, JSON salvage incl. truncation).
- RESULTS: test_script_robust 24 PASS / 0 FAIL; real `pipeline.py --project video_003 --resume` -> SCRIPT completed attempt 1 (9 scenes) -> COMPLETED end-to-end, `final_video.mp4` 35.858s h264+aac (voice+BGM, captions overlaid). Regressions: P2-SEP 22 PASS, P2-VISUAL/P2-CHUNKS/P2-RESUME/RESUME PASS, P3-A/P3-B ALL PASS, P4-REVIEW 0 failures, P4-DASH 31/31, script quick PASS. Part 2 visual/text separation untouched; human review + manual YouTube publishing unchanged.


# Completed tasks (Part 4 Prompt 2, 2026-09-14)
- Human review workflow: app/dashboard/review.py state machine (NOT_READY/PENDING/APPROVED/REJECTED) on existing StateManager (atomic writes, history append, is_approved_for_publishing()).
- APIs: POST review/approve|reject|reset (reject requires note; reset only from APPROVED/REJECTED), GET projects/{id}/video (project-only final video, Range, traversal-safe); GET /projects adds review_status; GET /projects/{id} adds review + seo.
- UI: Human Review section (badge, note field, confirm dialogs, history), Video Review section (<video> player + duration/size), NOT_READY disables actions. Fixed Prompt 1 innerHTML issue with full esc() escaping.
- Reviewer = "local_user" constant (not auth). Review actions logged via existing logger ([REVIEW] ...).
- No auto-approval anywhere; APPROVED/REJECTED survive refresh; old projects derive PENDING/NOT_READY without rewriting state.
- tests/test_p4_review.py ALL PASS; regressions: test_p4_dashboard 31/31, test_p4_live 8/8, test_resume PASS, test_p2_e2e PASS, test_p3_a/b ALL PASS.

# Completed tasks (Part 4 Prompt 3, 2026-09-14)
- app/youtube/: oauth.py (installed-app OAuth via google-auth-oauthlib, token refresh, redacted errors, channel query), uploader.py (upload gate re-check, metadata build from existing Part 3 seo.json, resumable upload, bounded transient retries, safe state updates via StateManager), test_client.py (deterministic mock, labelled TEST YOUTUBE MODE — NO REAL UPLOAD).
- APIs: GET /api/v1/dashboard/youtube/status; GET /projects/{id}/youtube/preview (blocked flag when not approved); POST /projects/{id}/youtube/upload (409 PROJECT_ALREADY_UPLOADED; 403 REVIEW_NOT_APPROVED; 401 NOT_AUTHENTICATED); POST /youtube/connect + /youtube/callback (OAuth code exchange).
- state.json youtube object: status NOT_READY/BLOCKED_REVIEW/BLOCKED_AUTH/READY/UPLOADING/UPLOADED/FAILED + video_id/url/privacy/title/uploaded_at — no secrets ever.
- Dashboard: YouTube section (connect/status, metadata preview, upload button with confirmation dialog, uploaded info). gitignore: *.token.json / token files.
- Tests test_p4_youtube.py: 58 PASS (OAuth status/refresh-mock/redaction, gate matrix, metadata, mock upload, duplicate 409, failures, security scan of state/API/HTML, API codes). Regressions: P4-review 0 failures, P4-dash 31/31, live 8/8, P1/P2/P3 PASS. NO real OAuth or upload executed.


- Dashboard foundation: FastAPI backend (app/dashboard/api.py + server.py) + service layer (service.py) + static frontend (static/index.html, style.css, app.js).
- APIs: GET /api/v1/dashboard/health, /projects, /projects/{id}, /projects/{id}/logs, /system; / serves frontend.
- Project browser (counts, table), detail view (info, 13-step pipeline incl. HUMAN_REVIEW, scene progress, artifacts, final video size/duration), log viewer (parse logs/pipeline.log, level/component/project filters).
- Reads existing state via ProjectManager; corrupt/missing state -> "State unavailable" without crashing; project-id validation blocks path traversal; zero AI generation in dashboard reads.
- Lightweight polling refresh (no SSE infra existed). Tests test_p4_dashboard.py (31/31) + test_p4_live.py (8/8, real uvicorn) + P1/P2/P3 regressions PASS.

# Completed tasks (Part 3, 2026-09-14)
- Research provider abstraction + test provider (deterministic, labelled) + YouTube Data API v3 provider (quota-aware, redaction, no scraping).
- Research engine: SHA-256 cached search (provider+query+region+language+max, TTL), bounded retries, per-query resume.
- Trend discovery: normalize + metrics (views/day, trend/freshness/engagement 0-100) + keyword aggregation.
- Deterministic topic scorer (formula documented), competition estimation (LOW/MEDIUM/HIGH + reasons), originality_check AND content-gap angles.
- Topic generator: compact summary -> llama3.2:3b (10-20 candidates) via centralized Ollama client + deterministic fallback.
- SEO engine: 3-5 titles + scoring, description, tags, keywords, hashtags, thumbnail concepts (text only).
- Pipeline steps RESEARCH->TOPIC_DISCOVERY->TOPIC_RANKING->TOPIC_SELECTED->SEO_GENERATION + research_report.md.
- CLI: --research/--query/--top/--select/--research-health/--force-research/--force-topic/--force-seo. Manual --topic skips P3 steps.
- Fixed pre-existing TTS bug: on audio cache HIT, dest copy was skipped -> project scene mp3 missing on resume. Fixed (Part 1 bug surfaced by P3 fix).
- Docs + .ai memory updated. All targeted tests PASS (see p3_*_out.txt).


