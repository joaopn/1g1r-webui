"""FastAPI application factory and the page routes."""

import re
import sqlite3
from collections.abc import Iterator
from contextlib import asynccontextmanager
from http import HTTPStatus
from importlib import resources
from typing import Annotated

import yaml
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from g1r import db, mounts
from g1r.config import Settings, load_settings
from g1r.library import FolderEntry, Library, LibraryStore

_WEB = resources.files("g1r").joinpath("web")
templates = Jinja2Templates(directory=str(_WEB.joinpath("templates")))

# Sidebar submenus: one entry per platform folder.
SECTIONS = [
    ("conversion", "Conversion"),
    ("matching", "Matching & 1G1R"),
    ("discarded", "Discarded"),
]

_LABEL_UNSAFE = re.compile(r"[^a-z0-9._-]+")


def suggest_label(path: str) -> str:
    name = path.rstrip("/").rsplit("/", 1)[-1].lower()
    return _LABEL_UNSAFE.sub("-", name).strip("-._")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    store = LibraryStore(settings)
    label_pattern = re.compile(settings.folders.label_pattern)
    platforms = settings.platforms.enabled_profiles()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Migrate once at start-up; requests then open their own connections.
        db.open_database(settings).close()
        store.load()  # fail fast on an invalid library.yaml
        yield

    def get_db() -> Iterator[sqlite3.Connection]:
        conn = db.connect(settings.paths.database_path, settings.database.busy_timeout_ms)
        try:
            yield conn
        finally:
            conn.close()

    app = FastAPI(title=settings.app.name, lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.store = store
    app.mount("/static", StaticFiles(directory=str(_WEB.joinpath("static"))), name="static")

    def folder_view(library: Library, folder: FolderEntry) -> dict:
        mount = next((m for m in mounts.list_mounts(settings) if m.id == folder.mount), None)
        location = None
        if mount is not None:
            location = str(mount.root / folder.path) if folder.path else str(mount.root)
        return {
            "label": folder.label,
            "platform": folder.platform,
            "platform_name": settings.platforms.profiles[folder.platform].name,
            "mount": folder.mount,
            "location": location,
            "on_main_mount": folder.mount == mounts.MAIN_MOUNT,
            "target": store.target_for(library, folder.platform),
        }

    def render(request: Request, template: str, active: str, **context) -> HTMLResponse:
        library = store.load()
        base = {
            "settings": settings,
            "sections": SECTIONS,
            "folders": [folder_view(library, f) for f in library.folders],
            "active": active,
            "active_folder": None,
        }
        return templates.TemplateResponse(request, template, {**base, **context})

    def partial(request: Request, template: str, **context) -> HTMLResponse:
        return templates.TemplateResponse(request, template, {"settings": settings, **context})

    # Pages ---------------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        return render(request, "home.html", "home")

    @app.get("/section/{section}", response_class=HTMLResponse)
    def section(request: Request, section: str):
        titles = dict(SECTIONS)
        if section not in titles:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND)
        return render(request, "section.html", section, title=titles[section])

    @app.get("/section/{section}/{label}", response_class=HTMLResponse)
    def folder_page(request: Request, section: str, label: str):
        titles = dict(SECTIONS)
        library = store.load()
        folder = library.folder(label)
        if section not in titles or folder is None:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND)
        view = folder_view(library, folder)
        return render(
            request,
            "folder.html",
            section,
            title=titles[section],
            folder=view,
            active_folder=label,
            target=settings.platforms.targets[view["target"]],
        )

    # Add platform ----------------------------------------------------------------

    def add_form(request: Request, *, error=None, values=None) -> HTMLResponse:
        values = values or {}
        mount_id = values.get("mount", mounts.MAIN_MOUNT)
        library = store.load()
        return partial(
            request,
            "add_platform.html",
            platforms=platforms,
            targets={p: store.target_for(library, p) for p in platforms},
            target_labels=settings.platforms.targets,
            mounts=mounts.list_mounts(settings),
            error=error,
            values=values,
            browser=browser_context(mount_id, values.get("path", "")),
        )

    def browser_context(mount_id: str, relative: str) -> dict:
        try:
            relative = mounts.normalise_relative(relative)
            mount = mounts.get_mount(settings, mount_id)
            children = mounts.subdirectories(settings, mount_id, relative)
            error = None
        except mounts.FolderPathError as exc:
            mount = mounts.get_mount(settings, mounts.MAIN_MOUNT)
            mount_id, relative, children, error = mount.id, "", [], str(exc)
        crumbs, walked = [], []
        for part in relative.split("/") if relative else []:
            walked.append(part)
            crumbs.append((part, "/".join(walked)))
        location = mount.root / relative if relative else mount.root
        return {
            "mount": mount_id,
            "path": relative,
            "location": str(location),
            "crumbs": crumbs,
            "children": children,
            "join": lambda child: f"{relative}/{child}" if relative else child,
            "suggested_label": suggest_label(relative) if relative else "",
            "error": error,
        }

    @app.get("/platforms/new", response_class=HTMLResponse)
    def add_platform_form(request: Request):
        return add_form(request)

    @app.get("/browse", response_class=HTMLResponse)
    def browse(request: Request, mount: str = mounts.MAIN_MOUNT, path: str = ""):
        return partial(request, "folder_browser.html", browser=browser_context(mount, path))

    @app.post("/platforms", response_class=HTMLResponse)
    def add_platform(
        request: Request,
        platform: Annotated[str, Form()] = "",
        mount: Annotated[str, Form()] = mounts.MAIN_MOUNT,
        path: Annotated[str, Form()] = "",
        label: Annotated[str, Form()] = "",
    ):
        values = {"platform": platform, "mount": mount, "path": path, "label": label}
        if platform not in platforms:
            return add_form(request, error="Choose a platform.", values=values)
        try:
            relative = mounts.normalise_relative(path)
            # Checked again under the library lock below; this gives the folder error first.
            mounts.check_new_folder(settings, mount, relative, store.load().folders)
        except mounts.FolderPathError as exc:
            return add_form(request, error=str(exc), values=values)
        label = label.strip() or suggest_label(relative)
        values["label"] = label
        if not label_pattern.match(label):
            return add_form(
                request,
                error="The label may use lowercase letters, digits, '.', '_' and '-' only.",
                values=values,
            )

        def change(library: Library) -> None:
            if library.folder(label):
                raise mounts.FolderPathError(f"the label {label!r} is already used")
            mounts.check_new_folder(settings, mount, relative, library.folders)
            library.folders.append(
                FolderEntry(label=label, platform=platform, mount=mount, path=relative)
            )

        try:
            store.update(change)
        except mounts.FolderPathError as exc:
            return add_form(request, error=str(exc), values=values)
        return Response(
            status_code=HTTPStatus.NO_CONTENT,
            headers={"HX-Redirect": f"/section/matching/{label}"},
        )

    @app.post("/folders/{label}/remove")
    def remove_folder(label: str):
        def change(library: Library) -> None:
            library.folders = [f for f in library.folders if f.label != label]

        store.update(change)
        return RedirectResponse("/", status_code=HTTPStatus.SEE_OTHER)

    # Settings ----------------------------------------------------------------------

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request, saved: str = ""):
        library = store.load()
        effective = yaml.safe_dump(settings.model_dump(mode="json"), sort_keys=False)
        return render(
            request,
            "settings.html",
            "settings",
            effective=effective,
            platforms=platforms,
            chosen={p: store.target_for(library, p) for p in platforms},
            target_labels=settings.platforms.targets,
            ignored="\n".join(store.ignored_filenames(library)),
            saved=saved,
        )

    @app.post("/settings/targets")
    async def save_targets(request: Request):
        form = await request.form()

        def change(library: Library) -> None:
            for platform, profile in platforms.items():
                value = form.get(f"target-{platform}")
                if value in profile.targets:
                    library.platform_targets[platform] = value

        store.update(change)
        return RedirectResponse("/settings?saved=targets#platforms", HTTPStatus.SEE_OTHER)

    @app.post("/settings/ignored")
    def save_ignored(ignored: Annotated[str, Form()] = ""):
        patterns = [line.strip() for line in ignored.splitlines() if line.strip()]

        def change(library: Library) -> None:
            library.ignored_filenames = patterns

        store.update(change)
        return RedirectResponse("/settings?saved=ignored#ignored", HTTPStatus.SEE_OTHER)

    @app.get("/healthz")
    def healthz(conn: Annotated[sqlite3.Connection, Depends(get_db)]):
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        return {"status": "ok", "schema_version": version}

    return app
