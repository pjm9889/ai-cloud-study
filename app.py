from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse


BASE_DIR = Path(__file__).resolve().parent
app = FastAPI(title="청년취업사관학교 새싹")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(BASE_DIR / "index.html")


@app.get("/{asset:path}")
async def assets(asset: str) -> FileResponse:
    requested = (BASE_DIR / asset).resolve()
    try:
        requested.relative_to(BASE_DIR)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Not found") from exc
    if not requested.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(requested)
