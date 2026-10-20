"""FastAPI application factory: the JSON API under /api, and the built web app at /.

The web app (React, in web/) is served from the same origin, so it needs no CORS and no
absolute URLs. Any path that is not an API route or an asset returns index.html, so a
deep link like /folders/nes/matching survives a reload.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import asynccontextmanager
from http import HTTPStatus
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from g1r import db, hasheous, journal, scanner
from g1r.config import Settings, load_settings
from g1r.dat_registry import DatRegistry, Fetch
from g1r.jobs import Jobs
from g1r.library import LibraryStore
from g1r.web.api import build_router


def create_app(
    settings: Settings | None = None,
    fetch: Fetch | None = None,
    report_runner: scanner.ReportRunner | None = None,
    lookup_post: hasheous.Post = hasheous.http_post,
) -> FastAPI:
    settings = settings or load_settings()
    store = LibraryStore(settings)
    registry = DatRegistry(settings, store, fetch)
    folder_scanner = scanner.Scanner(
        settings,
        store,
        registry,
        report_runner,
        lookup_post=lookup_post,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Migrate once at start-up; requests then open their own connections.
        conn = db.open_database(settings)
        scanner.fail_interrupted(conn)
        journal.recover(settings.apply, conn)
        registry.recheck_names(conn)
        conn.close()
        store.load()  # fail fast on an invalid library.yaml
        app.state.jobs = Jobs(settings, folder_scanner)
        yield
        app.state.jobs.shutdown()

    def get_db() -> Iterator[sqlite3.Connection]:
        conn = db.connect(settings.paths.database_path, settings.database.busy_timeout_ms)
        try:
            yield conn
        finally:
            conn.close()

    app = FastAPI(title=settings.app.name, lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.include_router(build_router(settings, store, registry, get_db), prefix="/api")

    @app.get("/healthz")
    def healthz(conn: Annotated[sqlite3.Connection, Depends(get_db)]):
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        return {"status": "ok", "schema_version": version}

    mount_web(app, settings)
    return app


# The page names the build's hashed assets, so the browser must ask again for it each time
# (a cached copy keeps running the previous build); the assets themselves never change.
INDEX_HEADERS = {"Cache-Control": "no-cache"}


def mount_web(app: FastAPI, settings: Settings) -> bool:
    """Serve the built web app with an index.html fallback. Call after the API routes."""
    dist = settings.paths.web_dist
    index = dist / "index.html"
    if not index.is_file():
        return False
    assets = dist / "assets"
    if assets.is_dir():
        # Hashed filenames: a missing asset is a 404, never index.html.
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def web_app(request: Request, path: str):
        if path == "api" or path.startswith("api/"):
            return JSONResponse({"detail": "not found"}, status_code=HTTPStatus.NOT_FOUND)
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and dist.resolve() in candidate.parents:
            return FileResponse(candidate, headers=INDEX_HEADERS)
        if "text/html" not in request.headers.get("accept", "text/html"):
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND)
        return FileResponse(index, headers=INDEX_HEADERS)

    return True
