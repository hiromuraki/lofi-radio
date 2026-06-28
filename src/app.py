import hashlib
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

# ── in-memory indexes ──────────────────────────────────────────────
image_index: dict[str, Path] = {}  # {sha256: path}
music_index: dict[str, dict] = {}  # {sha256: {"path": ..., "title": ...}}


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

# ── API routes (registered BEFORE the static mount) ────────────────

@app.get("/musiclist")
async def music_list():
    """Return all discovered music tracks with their SHA256 hashes."""
    return [
        {"sha256": sha, "title": info["title"]}
        for sha, info in music_index.items()
    ]


@app.get("/imagelist")
async def image_list():
    """Return all discovered images with their SHA256 hashes."""
    return [{"sha256": sha} for sha in image_index]


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

# ── static files (must be mounted last so API routes take priority) ─

app.mount("/", StaticFiles(directory=str(BASE_DIR / "static"), html=True), name="static")
