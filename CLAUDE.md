# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Lo-Fi Radio web player with a flat glassmorphism UI and CRT beam-collapse power-on/off animation. The frontend is a self-contained HTML/CSS/JS page served by a FastAPI backend that indexes media from `data/` at startup and serves them via SHA256-addressed API routes. Also includes a real-time chat room (SSE) and an ambient mixer placeholder panel.

## Commands

```bash
# Install dependencies
uv sync

# Start dev server (hot reload on)
uv run uvicorn src.app:app --host 0.0.0.0 --port 8000 --reload
# or
./run.sh
```

## Architecture

```text
src/app.py              # FastAPI backend — media indexing + API routes + chat SSE + static mount
static/index.html       # Single-page radio UI (HTML + CSS + JS inline, ~800 lines)
static/fonts/           # Local Inter font files (300/400/500/600 — no CDN dependency)
data/music/*.mp3        # Audio source files (3 tracks)
data/image/*.jpg        # Image source files (2 images)
run.sh                  # Startup helper
```

### Backend (`src/app.py`)

- **Startup**: Scans `data/music/` and `data/image/`, computes SHA256 of each file, builds in-memory indexes.
  - `image_index: dict[str, Path]` — `{sha256: filepath}`
  - `music_index: dict[str, dict]` — `{sha256: {"path": str, "title": str}}`
- **Media routes** (registered before static mount):
  - `GET /musiclist` → `[{"sha256":..., "title":...}, ...]`
  - `GET /imagelist` → `[{"sha256":...}, ...]`
  - `GET /music/{sha256}` → `FileResponse` (audio/mpeg)
  - `GET /image/{sha256}` → `FileResponse`
- **Chat routes** (in-memory, no persistence):
  - `POST /chat/send` — receive `{"content":"..."}` (1–256 chars), broadcast via SSE
  - `GET /chat/whoami` — return `{"ip":"x.x.x.x"}` so clients know their own messages
  - `GET /chat/stream` — SSE endpoint: replays last 10 messages on connect, then live push
  - Shared state: `chat_messages: list[dict]` + `sse_queues: list[asyncio.Queue]`
- **Static mount**: `StaticFiles` at `/` with `html=True` (must be last so API routes take priority).
- Uses FastAPI `lifespan` context manager for startup indexing.

### Frontend (`static/index.html`)

Single-file vanilla JS app — no build step, no framework.

**Layout** (absolute positioning over full-viewport CRT bezel):

| Element | Position | Style |
|---------|----------|-------|
| `.crt-bezel` | `absolute, inset:0` | Dark background, `overflow:hidden` |
| `.top-bar` | absolute, top-center | Glass (clock + signal dot) |
| `.song-bar` | absolute, bottom-center | Glass (marquee track title) |
| `.controls` | absolute, bottom-center | Glass (power, tuner, volume, fullscreen) |
| `.chat-panel` | absolute, right side, 260px | Transparent — bubbles only |
| `.ambient-toggle` | `fixed`, left edge, vertical | Accent tab, opens flyout |
| `.ambient-panel` | `fixed`, left 0, 33vw | Glass flyout, 5 dummy sliders |

**CRT effect**: Two-layer structure for beam collapse:
- `.crt-bezel` — dark bezel with `overflow:hidden` (clips expanding beam)
- `.crt-content` — animation target: `body.power-on` → `crt-on` keyframes; `body.power-off` → `crt-off`. Uses `scale(0, 0.005)` → `scale(1, 1)` with `brightness()` ramp to simulate cathode ray beam.

**Audio engine**: Dual `<audio>` element pool. Active plays, standby pre-fetches next track when `duration - currentTime ≤ 10`. On `ended`, roles swap for near-seamless transitions.

**Tuning flow**:
1. Slider input → pause audio, show static noise, update frequency display
2. 600ms debounce → frequency value as seed (mulberry32 PRNG) → Fisher-Yates shuffle playlist
3. Load first track from shuffled order, play, pick random image from `/imagelist`

**Chat**: SSE connection on power-on (`EventSource`). Messages stored client-side capped at 20. Own IP fetched from `/chat/whoami` — self messages bubble right (accent-tinted), others left. Text-only, 256-char limit, no persistence.

**Power lifecycle**:
- `powerOn()` → `body.className = "power-on"` → CRT animation → `connectChat()` + fetch indexes → play
- `powerOff()` → `body.className = "power-off"` → CRT collapse → `disconnectChat()` → clear art after animation
