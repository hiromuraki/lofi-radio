import asyncio
import hashlib
import json
import os
import random
import uuid
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import Scope

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))

# ── in-memory indexes ──────────────────────────────────────────────
image_index: dict[str, Path] = {}  # {sha256: path}
music_index: dict[str, dict] = {}  # {sha256: {"path": ..., "title": ...}}

# ── chat state ────────────────────────────────────────────────────
chat_messages = deque(maxlen=64)  # latest 64 messages (auto-evict)
sse_queues: list[asyncio.Queue] = []  # one queue per connected SSE client


async def _chat_broadcast(msg: dict) -> None:
    """Push *msg* to every connected SSE client."""
    for q in sse_queues:
        await q.put(msg)


def _sha256(filepath: Path) -> str:
    """Return the lowercase hex SHA256 digest of *filepath*."""
    sha = hashlib.sha256()
    with open(filepath, "rb") as fh:
        while chunk := fh.read(65536):
            sha.update(chunk)
    return sha.hexdigest()


def _build_indexes() -> None:
    """Walk `data/` and rebuild the in-memory indexes."""
    image_index.clear()
    music_index.clear()

    img_dir = DATA_DIR / "image"
    if img_dir.is_dir():
        for fp in sorted(img_dir.iterdir()):
            if fp.is_file():
                image_index[_sha256(fp)] = fp

    music_dir = DATA_DIR / "music"
    if music_dir.is_dir():
        for fp in sorted(music_dir.iterdir()):
            if fp.is_file() and fp.suffix.lower() in (".mp3", ".m4a", ".ogg", ".wav", ".flac"):
                music_index[_sha256(fp)] = {"path": str(fp), "title": fp.stem}


@asynccontextmanager
async def lifespan(app: FastAPI):
    _build_indexes()
    yield


app = FastAPI(title="Lo-Fi Radio", lifespan=lifespan)


# ── middleware: patch client IP from X-Forwarded-For ──────────────
class ProxyHeadersFix(BaseHTTPMiddleware):
    """Read X-Forwarded-For header and patch scope["client"] so
    req.client.host returns the real client IP even when uvicorn's
    --proxy-headers flag doesn't work."""

    async def dispatch(self, request: Request, call_next):
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            # Use the leftmost (original client) IP
            client_ip = forwarded.split(",")[0].strip()
            # Patch the ASGI scope in place
            request.scope["client"] = (client_ip, 0)
        return await call_next(request)


app.add_middleware(ProxyHeadersFix)

# ── API routes (registered BEFORE the static mount) ────────────────


MAX_ITEMS = 64


def _seeded_sample(population: list, seed: int, k: int = MAX_ITEMS) -> list:
    """Return a deterministically shuffled sample of up to *k* items."""
    rng = random.Random(seed)
    items = list(population)
    rng.shuffle(items)
    return items[:k]


@app.get("/musiclist")
async def music_list(freq: int = 0):
    """Return up to 64 music tracks shuffled with *freq* as seed."""
    entries = [{"sha256": sha, "title": info["title"]} for sha, info in music_index.items()]
    return _seeded_sample(entries, freq)


@app.get("/imagelist")
async def image_list(freq: int = 0):
    """Return up to 64 images shuffled with *freq* as seed."""
    entries = [{"sha256": sha} for sha in image_index]
    return _seeded_sample(entries, freq)


@app.get("/music/{sha256}")
async def music_file(sha256: str):
    """Serve a raw audio file by its SHA256 hash."""
    info = music_index.get(sha256)
    if info is None:
        raise HTTPException(status_code=404, detail="Music not found")
    return FileResponse(info["path"], media_type="audio/mpeg")


@app.get("/image/{sha256}")
async def image_file(sha256: str):
    """Serve a raw image file by its SHA256 hash."""
    fp = image_index.get(sha256)
    if fp is None:
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(fp)


# ── chat routes ───────────────────────────────────────────────────


@app.post("/chat/send")
async def chat_send(req: Request):
    """Receive a chat message and broadcast it via SSE."""
    body = await req.json()
    content = (body.get("content") or "").strip()
    if not content or len(content) > 256:
        raise HTTPException(status_code=400, detail="Content must be 1–256 characters")
    msg = {
        "id": str(uuid.uuid4()),
        "content": content,
        "sender_ip": req.client.host if req.client else "unknown",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    chat_messages.append(msg)
    # deque(maxlen=64) auto-evicts oldest on append

    await _chat_broadcast(msg)
    return {"ok": True}


@app.get("/chat/whoami")
async def chat_whoami(req: Request):
    """Return the client's IP as seen by the server."""
    return {
        "ip": req.client.host if req.client else "unknown",
        "x_forwarded_for": req.headers.get("X-Forwarded-For", "(missing)"),
        "x_real_ip": req.headers.get("X-Real-IP", "(missing)"),
    }


@app.get("/chat/stream")
async def chat_stream(last_id: str = ""):
    """SSE endpoint — incremental push based on last_id, then live messages.

    - If last_id is given and found in recent 5 messages, pushes only newer ones.
    - Otherwise pushes the last 5 messages.
    - Sends a heartbeat comment (": heartbeat") every 25 seconds."""

    COUNT = 5

    async def _event_stream():
        queue: asyncio.Queue = asyncio.Queue()
        sse_queues.append(queue)

        # Heartbeat: keep the connection alive
        async def heartbeat():
            while True:
                await asyncio.sleep(25)
                await queue.put(None)  # sentinel for heartbeat

        heartbeat_task = asyncio.create_task(heartbeat())

        try:
            # Convert to list for slicing (deque doesn't support slices)
            msgs = list(chat_messages)

            if last_id:
                # Search from the end for the last_id
                idx = -1
                for i in range(len(msgs) - 1, max(len(msgs) - COUNT - 1, -1), -1):
                    if msgs[i]["id"] == last_id:
                        idx = i
                        break
                replay = msgs[idx + 1 :] if idx >= 0 else msgs[-COUNT:]
            else:
                replay = msgs[-COUNT:]

            for msg in replay:
                yield f"data: {json.dumps(msg)}\n\n"

            # Stream live messages + heartbeat
            while True:
                msg = await queue.get()
                if msg is None:
                    # SSE comment — heartbeat, silently ignored by browser
                    yield ": heartbeat\n\n"
                else:
                    yield f"data: {json.dumps(msg)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            heartbeat_task.cancel()
            sse_queues.remove(queue)

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── static files (must be mounted last so API routes take priority) ─

app.mount("/", StaticFiles(directory=str(BASE_DIR / "static"), html=True), name="static")
