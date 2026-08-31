"""Application entrypoint. Wires the API, the static UI, and the worker thread."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import router
from .auth import require_token, verify_startup
from .config import settings
from .db import init_db
from .runner import runner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

STATIC_DIR = Path(__file__).parent / "static"

settings.screenshots_dir.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    verify_startup()
    init_db()
    runner.start()
    try:
        yield
    finally:
        runner.stop()


app = FastAPI(
    title="LinkedIn Profile Scraper",
    version=__version__,
    summary="Self-hosted profile scraping agents with scheduling, quotas, and CSV export.",
    lifespan=lifespan,
)

if settings.origins:
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Api-Token"],
    )

app.include_router(router, dependencies=[Depends(require_token)])
app.mount("/pictures", StaticFiles(directory=settings.screenshots_dir), name="pictures")
app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")


@app.get("/healthz")
def healthz() -> dict[str, object]:
    return {
        "ok": True,
        "version": __version__,
        "worker_alive": runner._thread.is_alive() if runner._thread else False,
        "current_launch": runner.current_launch_id,
    }


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str) -> FileResponse:
    """Client-side routing: every non-API path returns the shell."""
    return FileResponse(STATIC_DIR / "index.html")


def run() -> None:
    import uvicorn

    uvicorn.run(
        "phantom.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    run()
