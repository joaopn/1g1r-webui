"""FastAPI application factory and the page routes."""

import sqlite3
from collections.abc import Iterator
from contextlib import asynccontextmanager
from http import HTTPStatus
from importlib import resources
from typing import Annotated

import yaml
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from g1r import db
from g1r.config import Settings, load_settings

_WEB = resources.files("g1r").joinpath("web")
templates = Jinja2Templates(directory=str(_WEB.joinpath("templates")))

# Sidebar submenus: one entry per platform folder (folders arrive in P1b).
SECTIONS = [
    ("conversion", "Conversion"),
    ("matching", "Matching & 1G1R"),
    ("discarded", "Discarded"),
]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Migrate once at start-up; requests then open their own connections.
        db.open_database(settings).close()
        yield

    def get_db() -> Iterator[sqlite3.Connection]:
        conn = db.connect(settings.paths.database_path, settings.database.busy_timeout_ms)
        try:
            yield conn
        finally:
            conn.close()

    app = FastAPI(title=settings.app.name, lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.mount("/static", StaticFiles(directory=str(_WEB.joinpath("static"))), name="static")

    def render(request: Request, template: str, active: str, **context) -> HTMLResponse:
        base = {"settings": settings, "sections": SECTIONS, "folders": [], "active": active}
        return templates.TemplateResponse(request, template, {**base, **context})

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        return render(request, "home.html", "home")

    @app.get("/section/{section}", response_class=HTMLResponse)
    def section(request: Request, section: str):
        titles = dict(SECTIONS)
        if section not in titles:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND)
        return render(request, "section.html", section, title=titles[section])

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request):
        effective = yaml.safe_dump(settings.model_dump(mode="json"), sort_keys=False)
        return render(request, "settings.html", "settings", effective=effective)

    @app.get("/healthz")
    def healthz(conn: Annotated[sqlite3.Connection, Depends(get_db)]):
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        return {"status": "ok", "schema_version": version}

    return app
