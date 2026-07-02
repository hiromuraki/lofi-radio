# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Lo-Fi Radio web player — CRT beam-collapse power-on/off animation, flat glassmorphism UI, single-file vanilla-JS frontend, FastAPI backend. Includes real-time chat (SSE) and ambient mixer placeholder.

## Commands

```bash
# Install dependencies
uv sync

# Dev server (hot reload)
./run.sh
# or manually:
DATA_DIR=./data uv run uvicorn src.app:app --host 0.0.0.0 --port 8000 --reload

# Container build & run (Podman)
podman build -t lofi-radio .
podman run -p 8092:8000 -v /path/to/data:/data lofi-radio
```

## Architecture

```text
src/app.py           # FastAPI — media indexing, API routes, chat SSE, static mount
static/index.html    # Single-page UI (HTML + CSS + JS inline)
static/icons.svg     # SVG sprite sheet (power, volume, fullscreen icons)
static/fonts/        # Local Inter (300/400/500/600) — zero CDN dependency
data/music/*.mp3     # Audio source files
data/image/*.jpg     # Image source files
Dockerfile           # Multi-stage uv-based container build
run.sh               # Dev startup (sets DATA_DIR=$(pwd)/data)
```

### Backend (`src/app.py`)

- **Startup** (lifespan): scans `$DATA_DIR/music/` and `$DATA_DIR/image/`, SHA256-hashes each file, builds in-memory indexes. Default `DATA_DIR=/data` (container), overridden by `run.sh` for local dev.
- **ProxyHeadersFix middleware**: reads `X-Forwarded-For` header and patches `scope["client"]` so `req.client.host` returns real client IP behind reverse proxy. Independent of uvicorn's `--proxy-headers`.
- **Media routes** (registered BEFORE static mount):
  - `GET /musiclist?freq=<int>` → up to 64 tracks, seeded-shuffled with `freq` as `random.Random` seed (deterministic per frequency)
  - `GET /imagelist?freq=<int>` → up to 64 images, same seeded shuffle
  - `GET /music/{sha256}` → `FileResponse` (audio/mpeg)
  - `GET /image/{sha256}` → `FileResponse`
- **Chat** (in-memory, no persistence):
  - `chat_messages = deque(maxlen=64)` — auto-evicts oldest
  - `POST /chat/send` — `{"content":"…"}` (1–256 chars), assigns UUID `id`, broadcasts via SSE
  - `GET /chat/whoami` — returns `ip`, `x_forwarded_for`, `x_real_ip` (debug)
  - `GET /chat/stream?last_id=<uuid>` — SSE: incremental push if `last_id` found in last 5, else replays last 5. Heartbeat `: heartbeat\n\n` every 25s.
- **Static mount**: `StaticFiles` at `/` with `html=True`, must be last so API routes take priority.

### Frontend (`static/index.html`)

Single-file, no build step, no framework.

**Layout** (z-index stack inside full-viewport `.crt-bezel`):

| Layer | z-index | What |
|-------|---------|------|
| `.art-bg` | 0 | Full-bleed dynamic background image |
| `.bg-overlay` | 1 | Dark glass overlay (`backdrop-filter: blur`) |
| `.layout-3col` | 2 | Logical 3-col flex (left 260px / center flex / right 260px) |
| `.scanlines` | 5 | CRT scanline overlay |
| `.static-noise` | 6 | Tuning static effect |

Floating elements at z-index 10: `.top-bar` (clock + signal), `.controls` (power/tuner/volume/fullscreen).

**Tuning** (frequency-driven, backend-seeded):
1. Slider input (87.5–108.0 MHz) → 600ms debounce → fetch `GET /musiclist?freq=<int>` + `GET /imagelist?freq=<int>`
2. Backend returns up to 64 items shuffled deterministically by `freq` seed
3. Frontend plays from `musicList[currentIdx]`, advances sequentially; `artIdx` cycles through `imageList`

**Audio engine**: Dual `<audio>` element pool — active plays, standby pre-fetches next track 10s before end via `timeupdate`. On `ended`, roles swap for near-seamless transitions.

**Chat**: SSE incremental reconnect (`?last_id=`). Client-side dedup by message UUID. Max 5 messages displayed, bottom-anchored (`::before` spring + `justify-content: flex-end` removed from scrollable container). Self vs other distinguished by IP match from `/chat/whoami`.

**Icons**: SVG sprite in `static/icons.svg` with `<symbol>` definitions for `#power`, `#volume-high/medium/low/mute`, `#fullscreen`, `#fullscreen-exit`. Referenced via `<svg><use href="/icons.svg#..."/></svg>`. Volume icon switches `href` based on level; fullscreen toggles on `fullscreenchange` event.

**Slider styling**:

- `input[type="range"]`: track fill via JS `linear-gradient` (accent color left of thumb), Firefox `-moz-` pseudo-elements
- Tuner: 6px track, 24×14px lozenge thumb + `ew-resize` cursor + faint tick marks (`.ctl-group-tuner::before`)
- Volume: 40px circle button, slider popup opens on hover (`.ctl-group-vol:hover .vol-popup`), click toggle fallback for touch
