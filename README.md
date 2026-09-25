# YT001 — Local YouTube Automation (v1.0.0)

## v1.0.0 — Initial stable pipeline release

The current release contains the existing working pipeline and the hybrid visual
architecture (stock photo/video + local assets + AI image fallback). Full flow:
`RESEARCH → TOPIC SELECTION → SCRIPT → TTS → BGM → MIX → VISUAL SOURCES → CHUNKS →
FINAL VIDEO → HUMAN REVIEW → APPROVED → MANUAL YOUTUBE UPLOAD`.

All supported `.env` variables are documented in `.env.example` (copy it to `.env` and
fill in your own keys — never commit real credentials).

Pipeline: `RESEARCH → TOPIC SELECTION → SCRIPT → TTS → BGM → MIX → VISUALS → CHUNKS → FINAL VIDEO → HUMAN REVIEW`.

## Parts 1 & 2 (kept, reused)
- Part 1: crash-safe state, SHA-256 cache, Ollama client, script validation, edge-TTS, BGM + mix.
- Part 2: visuals (test/comfyui providers), Ken Burns chunks, final concat.
- Manual `python pipeline.py --project video_001 --topic "..."` still works (skips research steps).

## Script generation (SCRIPT) — long-form reliability

The SCRIPT step produces a structured JSON script whose **spoken narration** is
**180–240 s (8–16 scenes, 15–25 s of narration per scene)** — measured from real
narration word count at `SCRIPT_WPS` (2.5 words/s), never from the model's own
`duration` guesses.

- Prompt states the budget in **words and seconds** with a 9-beat narrative
  structure (hook → problem → why → core concept → technique → example →
  mistake → action plan → takeaway) and demands 8+ fully developed scenes.
- Validation order: JSON syntax → top-level fields → `scenes` list → scene count →
  per-scene narration → `visual_direction` → duration (`estimated_duration_seconds`
  is **derived** from the narration when missing, never from visuals) → total
  seconds → per-scene clamp.
- Empty narration is **fatal** (never patched); a too-short script is retried with
  the **measured** length and an explicit expansion instruction; the last attempt
  can complete a script locally by re-splitting over-long scenes (no invented text).
- `parse_script_json()` tolerates ```json fences, prose around the object,
  reasoning `<think>` traces, trailing commas, missing final `]`/`}` and a
  half-written trailing scene (dropped, never completed). Nothing is silently
  rewritten.
- `SCRIPT_MODEL` (default `llama3.2:3b`) selects the model; when it is not
  installed the pipeline falls back to `OLLAMA_TEXT_MODEL`. Reasoning builds are
  called in **plain mode** automatically (`json_mode_supported()`), because
  `deepseek-r1:7b` returns an empty `{}` under Ollama's JSON mode.
- Related keys: `SCRIPT_JSON_MODE`, `SCRIPT_NUM_CTX`, `SCRIPT_MAX_TOKENS`,
  `SCRIPT_EXPAND_RETRIES`, `SCRIPT_MIN_SCENES`, `SCRIPT_MAX_SCENES`,
  `SCRIPT_NARRATION_MIN_SECONDS`, `SCRIPT_NARRATION_MAX_SECONDS`, `OLLAMA_TIMEOUT`.

Tests: `python tests/test_script_longform.py` (cases A–L + JSON-mode routing,
deterministic mocks, no Ollama) and `python tests/test_script_robust.py`.

- **Research provider abstraction** (`app/research/`): `research_provider.py` Protocol, `test_provider.py`
  (deterministic, clearly labelled **TEST DATA — NOT REAL YOUTUBE DATA**), `youtube_provider.py`
  (official YouTube Data API v3, quota-aware, never scraps/bypasses).
- **Research engine**: quota-safe cached search (SHA-256 key = provider+query+region+language+max_results,
  TTL=`RESEARCH_CACHE_TTL_HOURS`), bounded retries, per-query resume, cache MISS→fetch / HIT→reuse.
- **Normalization + metrics** (`trend_discovery.py`): views/day, trend/freshness/engagement scores (0–100, deterministic).
- **Trend discovery**: query keyword aggregation, top patterns, configurable `RESEARCH_QUERIES`.
- **Topic candidates** (`topic_generator.py`): compact LLM summary → llama3.2:3b via centralized client
  (10–20 candidates), deterministic fallback when Ollama is down.
- **Deterministic scoring** (`topic_scorer.py`), see formula below; predicts nothing, internal priority only.
- **Competition estimation**: LOW/MEDIUM/HIGH with reasons (transparent, data-backed wording).
- **Content gap + originality guard**: gap angles + `originality_check` heuristic (not a legal guarantee).
- **SEO** (`seo_engine.py`): 3–5 title options + scoring, description, tags, keywords, hashtags, thumbnail concepts (text only, no Part 4 generation).
- **Outputs** in `projects/<id>/research/`: `trends.json`, `topics.json`, `ranked.json`,
  `selected_topic.json`, `seo.json`, `research_report.md` (explains WHY a topic was chosen).
- Native default niche is **Modern Stoicism + Applied Psychology**, fully configurable.

## Scoring formula (documented, internal heuristic)
```
score = 0.25*trend + 0.20*freshness + 0.20*search_intent + 0.15*engagement
        + 0.10*content_gap + 0.10*originality − competition/10
```
Component scores stored on each candidate so users can see WHY it ranked.

## Configuration (.env) — new Part 3 keys
```
CHANNEL_NICHE=Modern Stoicism and Applied Psychology
CHANNEL_LANGUAGE=en
TARGET_COUNTRY=US
RESEARCH_REGION=US
TARGET_AUDIENCE=Adults interested in self improvement
RESEARCH_PROVIDER=test            # test | youtube
TEST_RESEARCH_MODE=true           # deterministic fake data, offline-friendly
YOUTUBE_API_KEY=                  # set this for real research
YOUTUBE_RESEARCH_ENABLED=false
RESEARCH_CACHE_TTL_HOURS=24
YOUTUBE_MAX_RESULTS=25
YOUTUBE_MAX_QUERIES_PER_RUN=10
TOPIC_COUNT=12
RESEARCH_QUERIES=stoicism anxiety,stoicism overthinking,...   # optional override
```

## YouTube API setup (real research)
1. Create a Google Cloud project, enable YouTube Data API v3, create an API key.
2. Put it in `.env`: `YOUTUBE_API_KEY=...`, `YOUTUBE_RESEARCH_ENABLED=true`, `RESEARCH_PROVIDER=youtube`, `TEST_RESEARCH_MODE=false`.
3. Quota is limited (search=100 units, videos=1 unit). The cache and bounded result/query counts keep calls low.
4. Without a key, research returns `DISABLED/NO_API_KEY` and the system still supports test mode and manual `--topic`.

## Run
```powershell
python pipeline.py --research                      # full research, show top 10
python pipeline.py --research --query "stoicism anxiety"
python pipeline.py --research --top 5
python pipeline.py --research --select 1           # select rank 1 + generate SEO
python pipeline.py --research-health
# Media pipeline (unchanged):
python pipeline.py --project video_001 --topic "Your topic"
```
`--force-research` / `--force-topic` / `--force-seo` bypass per-step cache (only used deliberately).

## Cache / resume
- Repeated identical research → cache HIT, no API/LLM recall.
- `RESEARCH → TOPIC_DISCOVERY → TOPIC_RANKING → TOPIC_SELECTED → SEO_GENERATION` are each resumable;
  a crash before SEO resumes at SEO. Manual `--topic` marks research steps skipped.

## Security & originality
- API key only in `.env` (git-ignored). Errors redact credentials.
- No transcript downloading, no copying competitor narration/structure, no scraping bypass.
- `originality_check` flags near-verbatim title similarity as a heuristic only.

## Troubleshooting
- `RESEARCH PROVIDER NOT CONFIGURED` → wrong `RESEARCH_PROVIDER`.
- YouTube `DISABLED`/`AUTH_OR_QUOTA` → set key, check quota, or use test mode.
- Independently verified: Parts 1/2 media pipeline still passes after Part 3.

## Part 4 Prompt 1 — Dashboard Foundation (new)

Local web dashboard (read-only; no generation, no upload, no auth yet).

### Run

```powershell
python -m app.dashboard.server        # http://127.0.0.1:8000
```

Config: `DASHBOARD_HOST`, `DASHBOARD_PORT` (`.env`), `LOGS_DIR` for `logs/pipeline.log`.

### Pages / APIs

- Main page: project counts (total/active/completed/failed), project table (id, topic, status, current step, %, scenes, updated), system status line.
- Project detail: info + selected topic, pipeline progress (all 13 steps incl. `HUMAN_REVIEW`), scene progress (`N / M completed` or "Not available"), artifacts (state/script/research/audio/visuals/chunks/output/final video), log viewer (timestamp/level/component/message, level filter).
- APIs (all read-only, no expensive AI calls):
  - `GET /api/v1/dashboard/health`
  - `GET /api/v1/dashboard/projects`
  - `GET /api/v1/dashboard/projects/{project_id}` (state, pipeline, scenes, artifacts, final video info, selected topic)
  - `GET /api/v1/dashboard/projects/{project_id}/logs?limit=&level=&component=`
  - `GET /api/v1/dashboard/system` (Ollama reachability check only — no model calls)
  - `GET /` serves the static frontend.

### Behavior

- Consumes existing `projects/*/state.json` via `ProjectManager`; works with any Parts 1–3 project; corrupt/missing state shows "State unavailable" without crashing the list.
- Live status = lightweight polling of read-only endpoints (no SSE/WebSocket infra exists).
- Security: project IDs validated (`^[A-Za-z0-9][A-Za-z0-9._-]*$`) — path traversal rejected; no secrets/`.env` exposed; no arbitrary file reads.
- Final video: shows availability + size + duration (from state if recorded, no ffprobe).

## Part 4 Prompt 2 — Human Review Workflow (new)

Human-in-the-loop approval gate on top of the read-only dashboard. **Approval ≠ upload** — it only marks
`review.status = APPROVED` in `state.json`; no YouTube API calls exist yet.

### Review states (stored in `state.json` → `review`)
- `NOT_READY` — no valid final video (missing/empty/corrupt state); actions disabled.
- `PENDING` — final video ready, awaiting human decision (derived for old projects; never persisted until an action).
- `APPROVED` — explicit human approval (future publishing prerequisite).
- `REJECTED` — human rejection (note required).

Rules: approval is ONLY via the explicit approve endpoint; nothing auto-approves; `APPROVED`/`REJECTED`
survive dashboard refresh; every action appends an immutable history entry (`APPROVED|REJECTED|RESET`,
reviewer, note, timestamp); reset sends APPROVED/REJECTED back to PENDING with a note.



### New endpoints
- `GET  /api/v1/dashboard/projects/{id}/video` — serves ONLY that project's `output/final_video.mp4`
  (Range supported, 404 when missing, traversal-safe).
- `POST /api/v1/dashboard/projects/{id}/review/approve` — body `{"note": "..."}` (note optional).
- `POST /api/v1/dashboard/projects/{id}/review/reject` — body `{"note": "..."}` (**note required**, 422 otherwise).
- `POST /api/v1/dashboard/projects/{id}/review/reset` — body `{"note": "..."}` (optional); APPROVED/REJECTED → PENDING.

`GET /projects` now includes `review_status`; `GET /projects/{id}` includes full `review` + `seo`.



### UI
- Project detail adds **Human Review** section (status badge, reviewer/note/time, note textarea,
  APPROVE/REJECT buttons with confirm dialogs, SEND BACK TO REVIEW, history list) and a
  **Video Review** section with an inline `<video>` player + duration/size.
- All rendering is HTML-escaped (`esc()` + `textContent`-style building) — fixes the Prompt 1 innerHTML issue.

### Implementation
- `app/dashboard/review.py` — pure review state machine on top of the existing `StateManager`
  (atomic save, history append, `is_approved_for_publishing()` helper for the future publisher).
- Review actions are logged via the existing logger (`[REVIEW] Human review ... for project ...`).

### Reviewer identity
`local_user` constant — **not authentication**; real auth comes in a later Part 4 prompt.

### Tests
`tests/test_p4_review.py` (init matrices, approve/reject/reset, invalid transitions, history,
refresh persistence, traversal, corrupt/missing state, API, video endpoint, frontend static checks)
— all PASS; Prompt 1 suite (31/31) + live E2E (8/8) + P1/P2/P3 regressions still PASS.

## Part 4 Prompt 3 — YouTube OAuth + Safe Upload Workflow (new)

Connect a YouTube account via OAuth 2.0 and upload approved videos. **No real OAuth/upload is performed
in tests** — a deterministic mock client (`TEST_YOUTUBE_MODE=true`) stands in.

### Endpoints
- `GET  /api/v1/dashboard/youtube/status` — safe connection status (never returns tokens).
- `POST /api/v1/dashboard/projects/{id}/youtube/connect` — start OAuth; returns authorization URL.
- `GET  /api/v1/dashboard/youtube/callback` — OAuth callback; stores tokens.
- `GET  /api/v1/dashboard/projects/{id}/youtube/preview` — metadata preview (title/desc/tags/privacy/video info); 409 if not approved, 401 if not authenticated, 404 if no video.
- `POST /api/v1/dashboard/projects/{id}/youtube/upload` — upload (idempotent: 409 if already uploaded; enforces the review gate + auth + video).

### Upload gate (no bypass)
Service **and** uploader independently enforce: valid project, `final_video.mp4` present, `is_approved_for_publishing(project_id) == "APPROVED"`, OAuth connected, `youtube.status != "UPLOADED"`. Default privacy = `private`.

### Credentials
- OAuth client secret file via `YOUTUBE_CLIENT_SECRET_FILE` (`.env`); tokens only in `YOUTUBE_TOKEN_FILE` (git-ignored).
- `state.json` → `youtube`: `{status, video_id, url, privacy_status, title, uploaded_at}` — **never** access/refresh tokens or secrets.

### Security
Secrets never appear in API responses, logs, state, dashboard HTML, or Git; project IDs validated; traversal blocked; no shell execution; bounded retries for transient failures.

### Setup (real use)
1. Google Cloud project → enable YouTube Data API v3 → OAuth consent screen → create OAuth client (Desktop/Installed app) → download JSON.
2. Set in `.env`: `YOUTUBE_UPLOAD_ENABLED=true`, `YOUTUBE_CLIENT_SECRET_FILE=...`, `YOUTUBE_TOKEN_FILE=...`, `YOUTUBE_DEFAULT_PRIVACY=private`.
3. Dashboard → Connect YouTube → authorize in browser → status shows Connected.

### Tests
`tests/test_p4_youtube.py` (58 cases: config/cred paths, auth states, review-gate 409s, duplicate 409, metadata from SEO, sanitization, API status codes, frontend markers, no-secret-leak checks) — **all PASS; no real OAuth/upload executed**.




