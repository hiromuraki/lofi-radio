# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Lo-Fi Radio web player with a flat glassmorphism UI and CRT beam-collapse power-on/off animation. The frontend is a self-contained HTML/CSS/JS page served by a FastAPI backend that indexes media files from `data/` at startup and serves them via SHA256-addressed API routes.

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
src/app.py              # FastAPI backend — media indexing + API routes + static mount
static/index.html       # Single-page radio UI (HTML + CSS + JS inline)
data/music/*.mp3        # Audio source files
data/image/*.jpg        # Image source files
run.sh                  # Startup helper
```

### Backend (`src/app.py`)

- **Startup**: Scans `data/music/` and `data/image/`, computes SHA256 of each file, builds in-memory indexes.
  - `image_index: dict[str, Path]` — `{sha256: filepath}`
  - `music_index: dict[str, dict]` — `{sha256: {"path": str, "title": str}}`
- **API routes** (registered before the static mount to take priority):
  - `GET /musiclist` → `[{"sha256": ..., "title": ...}, ...]`
  - `GET /imagelist` → `[{"sha256": ...}, ...]`
  - `GET /music/{sha256}` → `FileResponse` (audio/mpeg)
  - `GET /image/{sha256}` → `FileResponse`
- **Static mount**: `StaticFiles` at `/` with `html=True` (serves `static/index.html` automatically).
- Uses FastAPI `lifespan` context manager for startup indexing.

### Frontend (`static/index.html`)

- **Design**: Flat/modern with glassmorphism panels (`backdrop-filter: blur`), dark background, system font stack (Inter).
- **CRT effect**: Beam collapse animation preserved (scale Y → 0.005 for power on/off), plus scanlines and static-noise overlays.
- **Audio engine**: Dual `<audio>` element pool for near-seamless track transitions.
- **Tuning flow**:
  1. User moves frequency slider → audio pauses, static noise shown, display updates.
  2. 600 ms debounce → frequency value used as seed (`Math.ceil(freq * 10)`) for seeded PRNG (mulberry32).
  3. Playlist shuffled via Fisher-Yates, first track loaded and played, random image displayed.
- **Pre-fetch**: When `duration - currentTime ≤ 10`, the standby audio element begins loading the next track URL, enabling gapless transitions.
- **Volume**: Real volume control (0–1 on both audio elements).
- **No build step, no framework** — all interactivity is vanilla JS in the browser.
