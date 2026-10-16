"""The JSON API the web app talks to. Every route is read-only towards ROM folders."""

import re
import sqlite3
from collections.abc import Callable
from http import HTTPStatus
from typing import Annotated

import yaml
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from g1r import matching, mounts, scanner
from g1r.config import RANKING_CRITERIA, RankingConfig, Settings
from g1r.dat_registry import DatRegistry, RegistryError
from g1r.library import FolderEntry, Library, LibraryStore
from g1r.ranking import LABELS as RANKING_LABELS

_LABEL_UNSAFE = re.compile(r"[^a-z0-9._-]+")


def suggest_label(path: str) -> str:
    name = path.rstrip("/").rsplit("/", 1)[-1].lower()
    return _LABEL_UNSAFE.sub("-", name).strip("-._")


def bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=message)


def not_found(message: str = "not found") -> HTTPException:
    return HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=message)


# Request bodies --------------------------------------------------------------------


class NewFolder(BaseModel):
    platform: str
    mount: str
    path: str
    label: str = ""


class KeepChoice(BaseModel):
    group_key: str
    rel_path: str | None


class LeaveAlone(BaseModel):
    group_key: str
    left: bool


class Targets(BaseModel):
    targets: dict[str, str]


class Ignored(BaseModel):
    patterns: list[str]


class ActiveVersion(BaseModel):
    version_id: int


class Pinned(BaseModel):
    pinned: bool


class FolderRanking(BaseModel):
    ranking: RankingConfig | None


# Serialisers -------------------------------------------------------------------------


def row_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def game_dict(game: matching.GameRow) -> dict:
    return {
        "key": game.group.key,
        "name": game.group.name,
        "source": game.group.source,
        "status": game.status,
        "reason": game.reason,
        "kept": game.kept.version.rel_path if game.kept else None,
        "candidates": sorted(game.candidates),
        "versions": [
            {
                "rel_path": row.version.rel_path,
                "game_name": row.version.game_name,
                "method": row.version.method,
                "probability": 1,
                "regions": list(row.version.parsed.regions),
                "languages": list(row.version.parsed.languages),
                "revision": row.version.parsed.revision,
                "prerelease": row.version.parsed.prerelease,
                "rerelease": row.version.parsed.rerelease,
                "tags": list(row.version.parsed.other_tags),
                "size": row.size,
                "keep": row.keep,
                "operation": row.operation,
            }
            for row in game.rows
        ],
    }


def build_router(
    settings: Settings,
    store: LibraryStore,
    registry: DatRegistry,
    get_db: Callable,
) -> APIRouter:
    router = APIRouter()
    platforms = settings.platforms.enabled_profiles()
    label_pattern = re.compile(settings.folders.label_pattern)
    Conn = Annotated[sqlite3.Connection, Depends(get_db)]

    def folder_or_404(label: str) -> FolderEntry:
        folder = store.load().folder(label)
        if folder is None:
            raise not_found(f"no folder {label!r}")
        return folder

    def folder_info(library: Library, folder: FolderEntry) -> dict:
        mount = next((m for m in mounts.list_mounts(settings) if m.id == folder.mount), None)
        location = None
        if mount is not None:
            location = str(mount.root / folder.path) if folder.path else str(mount.root)
        return {
            "label": folder.label,
            "platform": folder.platform,
            "mount": folder.mount,
            "path": folder.path,
            "location": location,
            "on_main_mount": folder.mount == mounts.MAIN_MOUNT,
            "target": store.target_for(library, folder.platform),
            "discarded_to": f"{settings.paths.discarded_root}/{folder.label}/",
        }

    # Meta ------------------------------------------------------------------------

    @router.get("/meta")
    def meta():
        return {
            "app": settings.app.model_dump(),
            "ui": settings.ui.model_dump(),
            "platforms": {
                pid: {
                    "name": p.name,
                    "short": p.short,
                    "kind": p.kind,
                    "nointro_dat": p.nointro_dat,
                    "rom_extensions": p.rom_extensions,
                    "targets": p.targets,
                    "default_target": p.default_target,
                }
                for pid, p in platforms.items()
            },
            "targets": {k: v.model_dump() for k, v in settings.platforms.targets.items()},
            "dat_sources": {k: v.model_dump() for k, v in settings.dats.sources.items()},
            "ranking": {
                "criteria": list(RANKING_CRITERIA),
                "labels": RANKING_LABELS,
                "default": settings.ranking.model_dump(),
            },
            "label_pattern": settings.folders.label_pattern,
            "discarded_root": str(settings.paths.discarded_root),
        }

    # Folders -----------------------------------------------------------------------

    @router.get("/folders")
    def list_folders(conn: Conn):
        library = store.load()
        result = []
        for folder in library.folders:
            table = matching.table(settings, conn, folder.label, store.ranking_for(folder))
            result.append(
                {
                    **folder_info(library, folder),
                    "scan": row_dict(scanner.latest_scan(conn, folder.label)),
                    "dat": row_dict(registry.active_version(conn, library, folder.platform)),
                    "summary": scanner.folder_summary(conn, folder.label),
                    "counts": table.counts,
                    "reclaim_bytes": table.reclaim_bytes,
                }
            )
        return result

    @router.post("/folders", status_code=HTTPStatus.CREATED)
    def add_folder(body: NewFolder):
        if body.platform not in platforms:
            raise bad_request("Choose a supported platform.")
        try:
            relative = mounts.normalise_relative(body.path)
            mounts.check_new_folder(settings, body.mount, relative, store.load().folders)
        except mounts.FolderPathError as exc:
            raise bad_request(str(exc)) from exc
        label = body.label.strip() or suggest_label(relative)
        if not label_pattern.match(label):
            raise bad_request("The label may use lowercase letters, digits, '.', '_' and '-' only.")

        def change(library: Library) -> None:
            if library.folder(label):
                raise mounts.FolderPathError(f"the label {label!r} is already used")
            mounts.check_new_folder(settings, body.mount, relative, library.folders)
            library.folders.append(
                FolderEntry(label=label, platform=body.platform, mount=body.mount, path=relative)
            )

        try:
            library = store.update(change)
        except mounts.FolderPathError as exc:
            raise bad_request(str(exc)) from exc
        return folder_info(library, library.folder(label))

    @router.delete("/folders/{label}", status_code=HTTPStatus.NO_CONTENT)
    def remove_folder(label: str):
        folder_or_404(label)
        store.update(
            lambda lib: setattr(lib, "folders", [f for f in lib.folders if f.label != label])
        )

    @router.get("/folders/{label}")
    def folder_detail(label: str, conn: Conn):
        folder = folder_or_404(label)
        library = store.load()
        return {
            **folder_info(library, folder),
            "dat": row_dict(registry.active_version(conn, library, folder.platform)),
            "scan": row_dict(scanner.latest_scan(conn, label)),
            "summary": scanner.folder_summary(conn, label),
            "unmatched": [dict(r) for r in scanner.unmatched_files(conn, label)],
            "others": [dict(r) for r in scanner.other_files(conn, label)],
            "ranking": store.ranking_for(folder).model_dump(),
            "ranking_is_default": folder.ranking is None,
        }

    @router.get("/folders/{label}/games")
    def folder_games(label: str, conn: Conn):
        folder = folder_or_404(label)
        games = matching.game_rows(settings, conn, label, store.ranking_for(folder))
        return [game_dict(g) for g in games]

    @router.put("/folders/{label}/keep")
    def keep(label: str, body: KeepChoice, conn: Conn):
        folder = folder_or_404(label)
        matching.set_keep(conn, label, body.group_key, body.rel_path)
        game = matching.find_game(settings, conn, label, store.ranking_for(folder), body.group_key)
        if game is None:
            raise not_found("no such game")
        return game_dict(game)

    @router.put("/folders/{label}/leave")
    def leave(label: str, body: LeaveAlone, conn: Conn):
        folder = folder_or_404(label)
        matching.set_left_alone(conn, label, body.group_key, body.left)
        game = matching.find_game(settings, conn, label, store.ranking_for(folder), body.group_key)
        if game is None:
            raise not_found("no such game")
        return game_dict(game)

    @router.put("/folders/{label}/ranking")
    def save_ranking(label: str, body: FolderRanking):
        folder_or_404(label)
        store.update(lambda lib: setattr(lib.folder(label), "ranking", body.ranking))
        return store.ranking_for(store.load().folder(label)).model_dump()

    # Scans -------------------------------------------------------------------------

    @router.post("/folders/{label}/scan", status_code=HTTPStatus.ACCEPTED)
    def start_scan(label: str, request: Request, conn: Conn):
        folder_or_404(label)
        try:
            request.app.state.jobs.scan(conn, label)
        except scanner.ScanError as exc:
            raise HTTPException(status_code=HTTPStatus.CONFLICT, detail=str(exc)) from exc
        return row_dict(scanner.latest_scan(conn, label))

    @router.get("/folders/{label}/scan")
    def scan_status(label: str, conn: Conn):
        folder_or_404(label)
        return row_dict(scanner.latest_scan(conn, label))

    # Mounts ------------------------------------------------------------------------

    @router.get("/mounts")
    def list_mounts():
        return [{"id": m.id, "root": str(m.root)} for m in mounts.list_mounts(settings)]

    @router.get("/browse")
    def browse(mount: str = mounts.MAIN_MOUNT, path: str = ""):
        try:
            relative = mounts.normalise_relative(path)
            root = mounts.get_mount(settings, mount).root
            children = mounts.subdirectories(settings, mount, relative)
        except mounts.FolderPathError as exc:
            raise bad_request(str(exc)) from exc
        return {
            "mount": mount,
            "path": relative,
            "location": str(root / relative) if relative else str(root),
            "children": children,
            "suggested_label": suggest_label(relative) if relative else "",
        }

    # Settings ------------------------------------------------------------------------

    @router.get("/settings")
    def get_settings():
        library = store.load()
        return {
            "targets": {p: store.target_for(library, p) for p in platforms},
            "ignored_filenames": store.ignored_filenames(library),
            "effective_yaml": yaml.safe_dump(settings.model_dump(mode="json"), sort_keys=False),
            "config_file": str(settings.paths.data_dir / settings.paths.user_config_file),
            "library_file": str(settings.paths.library_path),
        }

    @router.put("/settings/targets")
    def save_targets(body: Targets):
        def change(library: Library) -> None:
            for platform, target in body.targets.items():
                if platform not in platforms or target not in platforms[platform].targets:
                    raise bad_request(f"{target!r} is not a target for {platform!r}")
                library.platform_targets[platform] = target

        store.update(change)
        return get_settings()

    @router.put("/settings/ignored")
    def save_ignored(body: Ignored):
        patterns = [p.strip() for p in body.patterns if p.strip()]
        store.update(lambda lib: setattr(lib, "ignored_filenames", patterns))
        return get_settings()

    # DATs ----------------------------------------------------------------------------

    @router.get("/dats")
    def list_dats(conn: Conn):
        library = store.load()
        return [
            {
                "platform": pid,
                "active": row_dict(registry.active_version(conn, library, pid)),
                "pinned": bool(library.dats.get(pid) and library.dats[pid].pinned),
                "versions": [dict(v) for v in registry.versions(conn, pid)],
                "folders": [f.label for f in library.folders if f.platform == pid],
            }
            for pid in platforms
        ]

    def registry_call(action):
        try:
            return action()
        except RegistryError as exc:
            raise bad_request(str(exc)) from exc

    async def read_upload(upload: UploadFile) -> bytes:
        limit = settings.dats.max_upload_bytes
        data = await upload.read(limit + 1)
        if len(data) > limit:
            raise bad_request("the file is larger than dats.max_upload_bytes")
        return data

    @router.post("/dats/{platform}/download")
    def dat_download(platform: str, conn: Conn):
        version_id = registry_call(lambda: registry.download_libretro(conn, platform))
        return {"version_id": version_id}

    @router.post("/dats/{platform}/upload")
    async def dat_upload(platform: str, conn: Conn, file: Annotated[UploadFile, File()]):
        data = await read_upload(file)
        version_id = registry_call(
            lambda: registry.add_upload(conn, platform, data, file.filename or "upload.dat")
        )
        return {"version_id": version_id}

    @router.post("/dats/pack")
    async def dat_pack(conn: Conn, file: Annotated[UploadFile, File()]):
        data = await read_upload(file)
        results = registry_call(lambda: registry.add_pack(conn, data))
        return [r.__dict__ for r in results]

    @router.put("/dats/{platform}/active")
    def dat_activate(platform: str, body: ActiveVersion, conn: Conn):
        registry_call(lambda: registry.activate(conn, platform, body.version_id))
        return {"ok": True}

    @router.put("/dats/{platform}/pin")
    def dat_pin(platform: str, body: Pinned):
        registry_call(lambda: registry.set_pinned(platform, body.pinned))
        return {"ok": True}

    return router
