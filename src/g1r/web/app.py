"""FastAPI application factory and the page routes."""

import re
import sqlite3
import urllib.parse
from collections.abc import Iterator
from contextlib import asynccontextmanager
from http import HTTPStatus
from importlib import resources
from typing import Annotated

import yaml
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from g1r import db, matching, mounts, scanner
from g1r.config import RANKING_CRITERIA, RankingConfig, Settings, load_settings
from g1r.dat_registry import DatRegistry, Fetch, RegistryError
from g1r.jobs import Jobs
from g1r.library import FolderEntry, Library, LibraryStore
from g1r.ranking import LABELS as ranking_labels

_WEB = resources.files("g1r").joinpath("web")
templates = Jinja2Templates(directory=str(_WEB.joinpath("templates")))

# Sidebar submenus: one entry per platform folder.
SECTIONS = [
    ("conversion", "Conversion"),
    ("matching", "Matching & 1G1R"),
    ("discarded", "Discarded"),
]

_LABEL_UNSAFE = re.compile(r"[^a-z0-9._-]+")


def human_bytes(value: int | None, base: int, units: list[str]) -> str:
    if value is None:
        return ""
    amount, unit = float(value), units[0]
    for unit in units:
        if amount < base or unit == units[-1]:
            break
        amount /= base
    return f"{int(amount)} {unit}" if unit == units[0] else f"{amount:.1f} {unit}"


def human_time(value: str | None) -> str:
    """'2026-10-16T19:59:08Z' -> '2026-10-16 19:59 UTC'."""
    if not value:
        return ""
    date, _, clock = value.rstrip("Z").partition("T")
    return f"{date} {clock.rsplit(':', 1)[0]} UTC" if clock else date


def suggest_label(path: str) -> str:
    name = path.rstrip("/").rsplit("/", 1)[-1].lower()
    return _LABEL_UNSAFE.sub("-", name).strip("-._")


def create_app(
    settings: Settings | None = None,
    fetch: Fetch | None = None,
    report_runner: scanner.ReportRunner | None = None,
) -> FastAPI:
    settings = settings or load_settings()
    templates.env.filters["bytes"] = lambda v: human_bytes(
        v, settings.ui.byte_unit_base, settings.ui.byte_units
    )
    templates.env.filters["when"] = human_time
    store = LibraryStore(settings)
    registry = DatRegistry(settings, store, fetch)
    folder_scanner = scanner.Scanner(settings, store, registry, report_runner)
    label_pattern = re.compile(settings.folders.label_pattern)
    platforms = settings.platforms.enabled_profiles()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Migrate once at start-up; requests then open their own connections.
        conn = db.open_database(settings)
        scanner.fail_interrupted(conn)
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
    def home(request: Request, conn: Annotated[sqlite3.Connection, Depends(get_db)]):
        library = store.load()
        cards = []
        for folder in library.folders:
            summary = scanner.folder_summary(conn, folder.label)
            result = matching.table(settings, conn, folder.label, store.ranking_for(folder))
            cards.append(
                {
                    "folder": folder_view(library, folder),
                    "scan": scanner.latest_scan(conn, folder.label),
                    "dat": registry.active_version(conn, library, folder.platform),
                    "summary": summary,
                    "counts": result.counts,
                    "reclaim": result.reclaim_bytes,
                }
            )
        return render(request, "home.html", "home", cards=cards)

    @app.get("/section/{section}", response_class=HTMLResponse)
    def section(request: Request, section: str):
        titles = dict(SECTIONS)
        if section not in titles:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND)
        return render(request, "section.html", section, title=titles[section])

    @app.get("/section/{section}/{label}", response_class=HTMLResponse)
    def folder_page(
        request: Request,
        section: str,
        label: str,
        conn: Annotated[sqlite3.Connection, Depends(get_db)],
        ranking_error: str = "",
        view: str = "all",
        q: str = "",
        page: int = 1,
    ):
        titles = dict(SECTIONS)
        library = store.load()
        folder = library.folder(label)
        if section not in titles or folder is None:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND)
        info = folder_view(library, folder)
        context = {
            "title": titles[section],
            "folder": info,
            "active_folder": label,
            "target": settings.platforms.targets[info["target"]],
            "dat": registry.active_version(conn, library, folder.platform),
            "dat_sources": settings.dats.sources,
            "scan": scanner.latest_scan(conn, label),
        }
        if section == "matching":
            ranking = store.ranking_for(folder)
            context |= {
                "summary": scanner.folder_summary(conn, label),
                "unmatched": scanner.unmatched_files(conn, label),
                "others": scanner.other_files(conn, label),
                "ranking": ranking,
                "ranking_is_default": folder.ranking is None,
                "criteria": RANKING_CRITERIA,
                "ranking_labels": ranking_labels,
                "ranking_error": ranking_error,
                **games_context(conn, label, ranking, view, q, page),
            }
        return render(request, "folder.html", section, **context)

    # Matching & 1G1R table ---------------------------------------------------------

    def games_context(conn, label, ranking, view, q, page) -> dict:
        result = matching.table(settings, conn, label, ranking, view=view, query=q, page=page)
        return {"table": result, "view": view, "q": q, "filters": matching.FILTERS, "label": label}

    def folder_or_404(label: str):
        folder = store.load().folder(label)
        if folder is None:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND)
        return folder

    @app.get("/folders/{label}/games", response_class=HTMLResponse)
    def games(
        request: Request,
        label: str,
        conn: Annotated[sqlite3.Connection, Depends(get_db)],
        view: str = "all",
        q: str = "",
        page: int = 1,
    ):
        folder = folder_or_404(label)
        ctx = games_context(conn, label, store.ranking_for(folder), view, q, page)
        return partial(request, "games_table.html", **ctx)

    def game_fragment(request, conn, folder, group_key):
        game = matching.find_game(
            settings, conn, folder.label, store.ranking_for(folder), group_key
        )
        if game is None:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND)
        return partial(request, "game_group.html", game=game, label=folder.label, open=True)

    @app.post("/folders/{label}/keep", response_class=HTMLResponse)
    def keep(
        request: Request,
        label: str,
        conn: Annotated[sqlite3.Connection, Depends(get_db)],
        group_key: Annotated[str, Form()],
        rel_path: Annotated[str, Form()] = "",
    ):
        folder = folder_or_404(label)
        matching.set_keep(conn, label, group_key, rel_path or None)
        return game_fragment(request, conn, folder, group_key)

    @app.post("/folders/{label}/leave", response_class=HTMLResponse)
    def leave(
        request: Request,
        label: str,
        conn: Annotated[sqlite3.Connection, Depends(get_db)],
        group_key: Annotated[str, Form()],
        left: Annotated[str, Form()] = "",
    ):
        folder = folder_or_404(label)
        matching.set_left_alone(conn, label, group_key, left == "on")
        return game_fragment(request, conn, folder, group_key)

    @app.post("/folders/{label}/ranking")
    async def save_ranking(request: Request, label: str):
        folder_or_404(label)
        form = await request.form()
        if form.get("reset"):
            new = None
        else:
            positions = []
            for name in RANKING_CRITERIA:
                value = form.get(f"pos-{name}", "")
                if value.isdigit():
                    positions.append((int(value), name))
            split = lambda text: [p.strip() for p in str(text).split(",") if p.strip()]  # noqa: E731
            try:
                new = RankingConfig(
                    criteria=[name for _, name in sorted(positions)],
                    regions=split(form.get("regions", "")),
                    languages=split(form.get("languages", "")),
                    multi_region=str(form.get("multi_region", "best")),
                )
            except ValueError as exc:
                query = urllib.parse.urlencode({"ranking_error": str(exc)})
                return RedirectResponse(
                    f"/section/matching/{label}?{query}#ranking", HTTPStatus.SEE_OTHER
                )

        def change(library: Library) -> None:
            library.folder(label).ranking = new

        store.update(change)
        return RedirectResponse(f"/section/matching/{label}#games", HTTPStatus.SEE_OTHER)

    # Scans -------------------------------------------------------------------------

    def scan_status(request: Request, conn, label: str, polling: bool) -> HTMLResponse:
        scan = scanner.latest_scan(conn, label)
        if polling and (scan is None or scan["status"] != "running"):
            return HTMLResponse("", headers={"HX-Refresh": "true"})
        return partial(request, "scan_status.html", scan=scan, label=label)

    @app.post("/folders/{label}/scan", response_class=HTMLResponse)
    def start_scan(
        request: Request, label: str, conn: Annotated[sqlite3.Connection, Depends(get_db)]
    ):
        if store.load().folder(label) is None:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND)
        error = None
        try:
            request.app.state.jobs.scan(conn, label)
        except scanner.ScanError as exc:
            error = str(exc)
        scan = scanner.latest_scan(conn, label)
        return partial(request, "scan_status.html", scan=scan, label=label, error=error)

    @app.get("/folders/{label}/scan-status", response_class=HTMLResponse)
    def get_scan_status(
        request: Request,
        label: str,
        conn: Annotated[sqlite3.Connection, Depends(get_db)],
        polling: bool = False,
    ):
        return scan_status(request, conn, label, polling)

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

    # DATs ------------------------------------------------------------------------

    async def read_upload(upload: UploadFile) -> bytes:
        limit = settings.dats.max_upload_bytes
        data = await upload.read(limit + 1)
        if len(data) > limit:
            raise RegistryError("the file is larger than dats.max_upload_bytes")
        return data

    def dats_redirect(message: str, error: bool = False, anchor: str = "") -> RedirectResponse:
        query = urllib.parse.urlencode({"error" if error else "msg": message})
        return RedirectResponse(f"/settings/dats?{query}#{anchor}", HTTPStatus.SEE_OTHER)

    @app.get("/settings/dats", response_class=HTMLResponse)
    def dats_page(
        request: Request,
        conn: Annotated[sqlite3.Connection, Depends(get_db)],
        msg: str = "",
        error: str = "",
    ):
        library = store.load()
        rows = []
        for pid, profile in platforms.items():
            active = registry.active_version(conn, library, pid)
            rows.append(
                {
                    "id": pid,
                    "profile": profile,
                    "active": active,
                    "pinned": bool(library.dats.get(pid) and library.dats[pid].pinned),
                    "versions": registry.versions(conn, pid),
                    "folders": [f.label for f in library.folders if f.platform == pid],
                }
            )
        return render(
            request,
            "dats.html",
            "settings",
            rows=rows,
            sources=settings.dats.sources,
            msg=msg,
            error=error,
        )

    @app.post("/dats/{platform}/download")
    def dat_download(platform: str, conn: Annotated[sqlite3.Connection, Depends(get_db)]):
        try:
            registry.download_libretro(conn, platform)
        except RegistryError as exc:
            return dats_redirect(f"{platform}: {exc}", error=True, anchor=platform)
        return dats_redirect(f"{platform}: libretro DAT downloaded", anchor=platform)

    @app.post("/dats/{platform}/upload")
    async def dat_upload(
        platform: str,
        conn: Annotated[sqlite3.Connection, Depends(get_db)],
        file: Annotated[UploadFile, File()],
    ):
        try:
            data = await read_upload(file)
            registry.add_upload(conn, platform, data, file.filename or "upload.dat")
        except RegistryError as exc:
            return dats_redirect(f"{platform}: {exc}", error=True, anchor=platform)
        return dats_redirect(f"{platform}: DAT uploaded", anchor=platform)

    @app.post("/dats/pack")
    async def dat_pack(
        conn: Annotated[sqlite3.Connection, Depends(get_db)],
        file: Annotated[UploadFile, File()],
    ):
        try:
            results = registry.add_pack(conn, await read_upload(file))
        except RegistryError as exc:
            return dats_redirect(f"pack: {exc}", error=True)
        added = [r for r in results if r.version_id]
        names = ", ".join(sorted({r.platform for r in added})) or "none"
        skipped = len(results) - len(added)
        return dats_redirect(f"pack: {len(added)} DATs added ({names}); {skipped} skipped")

    @app.post("/dats/{platform}/activate")
    def dat_activate(
        platform: str,
        conn: Annotated[sqlite3.Connection, Depends(get_db)],
        version_id: Annotated[int, Form()],
    ):
        try:
            registry.activate(conn, platform, version_id)
        except RegistryError as exc:
            return dats_redirect(f"{platform}: {exc}", error=True, anchor=platform)
        return dats_redirect(f"{platform}: active DAT changed", anchor=platform)

    @app.post("/dats/{platform}/pin")
    def dat_pin(platform: str, pinned: Annotated[str, Form()] = ""):
        try:
            registry.set_pinned(platform, pinned == "on")
        except RegistryError as exc:
            return dats_redirect(f"{platform}: {exc}", error=True, anchor=platform)
        return dats_redirect(
            f"{platform}: {'pinned' if pinned == 'on' else 'unpinned'}", anchor=platform
        )

    @app.get("/healthz")
    def healthz(conn: Annotated[sqlite3.Connection, Depends(get_db)]):
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        return {"status": "ok", "schema_version": version}

    return app
