"""The JSON API the web app talks to. Every route is read-only towards ROM folders."""

import re
import sqlite3
from collections.abc import Callable
from dataclasses import asdict
from http import HTTPStatus
from typing import Annotated

import yaml
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from g1r import (
    automatch,
    conversion,
    dashboard,
    decrypt,
    discarded,
    filecache,
    journal,
    matching,
    mounts,
    scanner,
    screenscraper,
    unmatched,
)
from g1r.config import RANKING_CRITERIA, RankingConfig, Settings
from g1r.dat_registry import DatRegistry, RegistryError, name_style
from g1r.library import FolderEntry, Library, LibraryStore
from g1r.ranking import LABELS as RANKING_LABELS

_LABEL_UNSAFE = re.compile(r"[^a-z0-9._-]+")


def suggest_label(path: str) -> str:
    name = path.rstrip("/").rsplit("/", 1)[-1].lower()
    return _LABEL_UNSAFE.sub("-", name).strip("-._")


class BatchError(Exception):
    """Some rows of a batch were refused: (path, reason) each."""

    def __init__(self, problems: list[tuple[str, str]]):
        super().__init__(f"{len(problems)} rows refused")
        self.problems = problems


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


class NewSet(BaseModel):
    path: str
    platform: str
    label: str


class NewSets(BaseModel):
    mount: str
    sets: list[NewSet]


class Hidden(BaseModel):
    hidden: bool


class ApplyScope(BaseModel):
    # One game, or the whole folder when None.
    group_key: str | None = None
    token: str | None = None


class ConvertScope(BaseModel):
    # Some files, or every proposed conversion when None.
    rel_paths: list[str] | None = None
    token: str | None = None
    # Typed folder label; needed when the plan deletes originals.
    confirm: str | None = None


class UnmatchedScope(BaseModel):
    rel_paths: list[str]
    # Delete for good (guarded) instead of moving to discarded/<label>/manual/.
    delete: bool = False
    token: str | None = None
    confirm: str | None = None


class Guarded(BaseModel):
    token: str | None = None
    confirm: str | None = None


class RestoreScope(BaseModel):
    operation_ids: list[int] | None = None
    group_key: str | None = None


class KeepChoice(BaseModel):
    group_key: str
    rel_path: str | None


class LeaveAlone(BaseModel):
    group_key: str
    left: bool


class ConversionOptions(BaseModel):
    delete_originals: bool


class Assignment(BaseModel):
    rel_path: str
    game_name: str | None


class Lookups(BaseModel):
    hasheous: bool | None = None
    screenscraper: bool | None = None


class ScreenScraperCredentials(BaseModel):
    """A field left out is kept; an empty one is removed."""

    devid: str | None = None
    devpassword: str | None = None
    user: str | None = None
    password: str | None = None


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
                "title": row.version.title or row.version.game_name,
                "method": row.version.method,
                "probability": row.probability,
                "regions": list(row.version.parsed.regions),
                "languages": list(row.version.parsed.languages),
                "revision": row.version.parsed.revision,
                "prerelease": row.version.parsed.prerelease,
                "rerelease": row.version.parsed.rerelease,
                "tags": list(row.version.parsed.other_tags),
                "size": row.size,
                "keep": row.keep,
                "operation": row.operation,
                "discarded": row.discarded,
                "identical": row.identical,
                "notes": row.notes,
                "role": row.version.role or None,
                "discard_reason": row.discard_reason if row.operation else None,
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
            "delete_originals": folder.delete_originals,
            "hidden": folder.hidden,
        }

    def parts_of(folder: FolderEntry) -> frozenset[str]:
        return frozenset(e.lower() for e in platforms[folder.platform].part_extensions)

    def produces(library: Library, folder: FolderEntry, conn) -> matching.FolderView:
        """The folder's platform as the 1G1R table sees it; names read as its active DAT's."""
        style = name_style(registry.active_version(conn, library, folder.platform))
        target = settings.platforms.targets[store.target_for(library, folder.platform)]
        profile = platforms[folder.platform]
        return matching.FolderView(
            target.produces,
            parts_of(folder),
            profile.names_from,
            profile.title_ids,
            style,
        )

    def conversion_rows(library: Library, folder: FolderEntry, conn) -> list:
        target = settings.platforms.targets[store.target_for(library, folder.platform)]
        try:
            root = mounts.resolve(settings, folder.mount, folder.path)
        except mounts.FolderPathError:
            root = None
        return conversion.rows(
            settings,
            conn,
            folder.label,
            folder.platform,
            target,
            delete_originals=folder.delete_originals,
            root=root if root is not None and root.is_dir() else None,
            # Only a card image's decryption needs the DAT here (it proves the result).
            dat=(
                registry.load_active(conn, library, folder.platform)
                if platforms[folder.platform].card_image
                else None
            ),
        )

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
                    "dat_name": p.dat_name,
                    "rom_extensions": p.rom_extensions,
                    "targets": p.targets,
                    "default_target": p.default_target,
                    "decrypts": p.decrypts,
                }
                for pid, p in platforms.items()
            },
            "targets": {k: v.model_dump() for k, v in settings.platforms.targets.items()},
            "archive_extensions": settings.platforms.archive_extensions,
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

    def default_download(platform: str) -> dict | None:
        """The first source the platform's DAT downloads from (as Settings → DATs lists them)."""
        sources = registry.downloads(platform) if platform in platforms else []
        if not sources:
            return None
        return {"source": sources[0], "label": settings.dats.sources[sources[0]].label}

    def screenscraper_offered(library, platform: str) -> bool:
        """ScreenScraper knows the platform but is not looking its files up."""
        if platform not in platforms or platforms[platform].screenscraper_id is None:
            return False
        configured = screenscraper.credentials(settings) is not None
        return not (configured and library.lookups.screenscraper)

    def title_ids(platform: str) -> bool:
        """The platform identifies by title ID, so a scan needs no DAT."""
        return platform in platforms and platforms[platform].title_ids

    @router.get("/folders")
    def list_folders(conn: Conn):
        library = store.load()
        result = []
        for folder in library.folders:
            table = matching.table(
                settings,
                conn,
                folder.label,
                store.ranking_for(folder),
                folder_view=produces(library, folder, conn),
            )
            info = folder_info(library, folder)
            scan = scanner.latest_scan(conn, folder.label)
            dat = registry.active_version(conn, library, folder.platform)
            summary = scanner.folder_summary(conn, folder.label, parts_of(folder))
            result.append(
                {
                    **info,
                    "scan": row_dict(scan),
                    "dat": row_dict(dat),
                    "summary": summary,
                    "dat_download": default_download(folder.platform) if dat is None else None,
                    "needs_dat": dat is None and not title_ids(folder.platform),
                    "counts": table.counts,
                    "reclaim_bytes": table.reclaim_bytes,
                    "conversion": conversion.counts(conversion_rows(library, folder, conn)),
                    "discarded": discarded.totals(settings, folder.label),
                    "warnings": dashboard.warnings(
                        conn,
                        folder.label,
                        location=info["location"],
                        platform_short=(
                            platforms[folder.platform].short
                            if folder.platform in platforms
                            else folder.platform
                        ),
                        scan=scan,
                        dat=dat,
                        unmatched=summary["unmatched"],
                        screenscraper_offered=screenscraper_offered(library, folder.platform),
                    ),
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
    def remove_folder(label: str, conn: Conn):
        """The set leaves the library; no file is touched (discarded/<label>/ stays)."""
        folder_or_404(label)
        busy = journal.busy(conn, label)
        if busy:
            raise HTTPException(status_code=HTTPStatus.CONFLICT, detail=busy)
        store.update(
            lambda lib: setattr(lib, "folders", [f for f in lib.folders if f.label != label])
        )
        filecache.forget(conn, label)

    @router.put("/folders/{label}/hidden")
    def hide_folder(label: str, body: Hidden):
        folder_or_404(label)
        library = store.update(lambda lib: setattr(lib.folder(label), "hidden", body.hidden))
        return folder_info(library, library.folder(label))

    # Sets from a folder of platform folders ------------------------------------------

    def unique_label(wanted: str, used: set[str]) -> str:
        label, n = wanted, 1
        while label in used:
            n += 1
            label = f"{wanted}-{n}"
        return label

    @router.get("/set-candidates")
    def set_candidates(mount: str = mounts.MAIN_MOUNT, path: str = ""):
        """Each subfolder of mount/path with the platform its name matches, a free label, and
        why it cannot be added when it cannot (already a set, or overlapping one)."""
        try:
            relative = mounts.normalise_relative(path)
            root = mounts.get_mount(settings, mount).root
            children = mounts.subdirectories(settings, mount, relative)
        except mounts.FolderPathError as exc:
            raise bad_request(str(exc)) from exc
        library = store.load()
        matcher = automatch.Matcher(platforms, settings.folders.unsupported_names)
        used = {f.label for f in library.folders}
        rows = []
        for name in children:
            child = f"{relative}/{name}" if relative else name
            found = matcher.match(name)
            try:
                target = mounts.check_new_folder(settings, mount, child, library.folders)
            except mounts.FolderPathError as exc:
                problem, items = str(exc), None
            else:
                problem = None
                items = sum(1 for e in target.iterdir() if not e.name.startswith("."))
            label = unique_label(suggest_label(child), used) if problem is None else ""
            used.add(label)
            rows.append(
                {
                    "name": name,
                    "path": child,
                    "platform": found.platform,
                    "note": found.note,
                    "label": label,
                    "problem": problem,
                    "items": items,
                }
            )
        return {
            "mount": mount,
            "path": relative,
            "location": str(root / relative) if relative else str(root),
            "rows": rows,
        }

    @router.post("/sets", status_code=HTTPStatus.CREATED)
    def add_sets(body: NewSets):
        """Add several sets at once: all of them, or none when any is refused."""

        def checked(library: Library) -> list[FolderEntry]:
            problems: list[tuple[str, str]] = []
            entries: list[FolderEntry] = []
            labels = {f.label for f in library.folders}
            for item in body.sets:
                try:
                    relative = mounts.normalise_relative(item.path)
                    label = item.label.strip() or suggest_label(relative)
                    if item.platform not in platforms:
                        raise mounts.FolderPathError("choose a supported platform")
                    if not label_pattern.match(label):
                        raise mounts.FolderPathError(
                            f"the label {label!r} may use lowercase letters, digits, "
                            "'.', '_' and '-' only"
                        )
                    if label in labels:
                        raise mounts.FolderPathError(f"the label {label!r} is already used")
                    # Earlier rows of this batch count as sets: no folder in two labels.
                    mounts.check_new_folder(
                        settings, body.mount, relative, [*library.folders, *entries]
                    )
                except mounts.FolderPathError as exc:
                    problems.append((item.path, str(exc)))
                    continue
                labels.add(label)
                entries.append(
                    FolderEntry(
                        label=label, platform=item.platform, mount=body.mount, path=relative
                    )
                )
            if problems:
                raise BatchError(problems)
            return entries

        if not body.sets:
            raise bad_request("choose at least one folder")
        added: list[str] = []

        def change(library: Library) -> None:
            entries = checked(library)
            library.folders.extend(entries)
            added.extend(e.label for e in entries)

        try:
            library = store.update(change)
        except BatchError as exc:
            detail = {
                "message": "nothing was added: some folders cannot be sets",
                "problems": [{"rel_path": p, "problem": text} for p, text in exc.problems],
            }
            raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=detail) from exc
        return [folder_info(library, library.folder(label)) for label in added]

    @router.get("/folders/{label}")
    def folder_detail(label: str, conn: Conn):
        folder = folder_or_404(label)
        library = store.load()
        return {
            **folder_info(library, folder),
            "dat": row_dict(registry.active_version(conn, library, folder.platform)),
            "scan": row_dict(scanner.latest_scan(conn, label)),
            "summary": scanner.folder_summary(conn, label, parts_of(folder)),
            "unmatched": [dict(r) for r in scanner.unmatched_files(conn, label, parts_of(folder))],
            "others": [dict(r) for r in scanner.other_files(conn, label)],
            "unsupported": scanner.unsupported_files(
                conn,
                label,
                platforms[folder.platform].rom_extensions,
                platforms[folder.platform].romsets,
            ),
            "ranking": store.ranking_for(folder).model_dump(),
            "ranking_is_default": folder.ranking is None,
        }

    @router.get("/folders/{label}/discarded")
    def folder_discarded(label: str, conn: Conn):
        folder = folder_or_404(label)
        info = folder_info(store.load(), folder)
        operations = {op["destination"]: op["id"] for op in journal.active_discards(conn, label)}
        reasons = discarded.listing(settings, label, info["location"], operations)
        return {
            "root": str(discarded.folder_root(settings, label)),
            "files": sum(len(r.files) for r in reasons),
            "bytes": sum(r.bytes for r in reasons),
            "reasons": [asdict(r) | {"bytes": r.bytes} for r in reasons],
        }

    # Apply and restore -----------------------------------------------------------

    def folder_root(folder: FolderEntry):
        try:
            return mounts.resolve(settings, folder.mount, folder.path)
        except mounts.FolderPathError as exc:
            raise conflict(str(exc)) from exc

    def conflict(message: str, problems=None) -> HTTPException:
        detail = {
            "message": message,
            "problems": [{"rel_path": rel, "problem": text} for rel, text in problems or []],
        }
        return HTTPException(status_code=HTTPStatus.CONFLICT, detail=detail)

    def discard_plan(conn, label: str, group_key: str | None):
        folder = folder_or_404(label)
        games = matching.game_rows(
            settings, conn, label, store.ranking_for(folder), produces(store.load(), folder, conn)
        )
        if group_key is not None:
            games = [g for g in games if g.group.key == group_key]
            if not games:
                raise not_found("no such game")
        root = folder_root(folder)
        plan = journal.plan_discards(conn, label, root, games)
        problems = journal.preflight(plan, root, discarded.folder_root(settings, label))
        return plan, problems

    def move_dict(m: journal.Move) -> dict:
        return {
            "rel_path": m.rel_path,
            "group_key": m.group_key,
            "action": m.action,
            "source": str(m.source),
            "destination": str(m.destination) if m.destination else None,
            "size": m.size,
        }

    def convert_plan(conn, label: str, rel_paths: list[str] | None):
        folder = folder_or_404(label)
        rows = conversion_rows(store.load(), folder, conn)
        if rel_paths is not None:
            wanted = set(rel_paths)
            rows = [r for r in rows if r.rel_path in wanted]
            if len(rows) != len(wanted):
                raise not_found("some of these files are not in the folder")
        root = folder_root(folder)
        plan = journal.plan_conversions(conn, label, root, rows)
        problems = journal.preflight(plan, root, discarded.folder_root(settings, label))
        return plan, problems

    def conversion_dict(plan: list[journal.Move]) -> list[dict]:
        """One entry per conversion: its output, and where its original goes."""
        result = []
        for m in plan:
            if m.action == journal.CONVERT:
                result.append({"rel_path": m.rel_path, "output": m.paired_rel, "size": m.size})
            elif m.follows:
                entry = result[-1]
                entry["originals"] = entry.get("originals", 0) + 1
                entry.setdefault("original_to", str(m.destination) if m.destination else None)
        return result

    @router.post("/folders/{label}/apply/preview")
    def apply_preview(label: str, body: ApplyScope, conn: Conn):
        plan, problems = discard_plan(conn, label, body.group_key)
        return {
            "token": journal.token(plan),
            "moves": [move_dict(m) for m in plan],
            "bytes": sum(m.size for m in plan),
            "problems": [{"rel_path": r, "problem": p} for r, p in problems],
            "busy": journal.busy(conn, label),
        }

    @router.post("/folders/{label}/apply", status_code=HTTPStatus.ACCEPTED)
    def apply(label: str, body: ApplyScope, request: Request, conn: Conn):
        def check():
            plan, problems = discard_plan(conn, label, body.group_key)
            if journal.token(plan) != body.token:
                raise journal.PlanError("the plan changed since you reviewed it; look again")
            if problems:
                raise journal.PlanError(
                    "nothing was moved: some files are not as scanned", problems
                )
            if not plan:
                raise journal.PlanError("there is nothing to apply")
            return plan

        try:
            run_id = request.app.state.jobs.apply(
                conn, label, journal.APPLY, body.group_key or "", check
            )
        except journal.PlanError as exc:
            raise conflict(str(exc), exc.problems) from exc
        return journal.progress(conn, run_id)

    @router.post("/folders/{label}/convert/preview")
    def convert_preview(label: str, body: ConvertScope, conn: Conn):
        plan, problems = convert_plan(conn, label, body.rel_paths)
        return {
            "token": journal.token(plan),
            "conversions": conversion_dict(plan),
            "irreversible": len(journal.irreversible(plan)),
            "bytes": sum(m.size for m in plan if m.action == journal.CONVERT),
            "problems": [{"rel_path": r, "problem": p} for r, p in problems],
            "busy": journal.busy(conn, label),
        }

    @router.post("/folders/{label}/convert", status_code=HTTPStatus.ACCEPTED)
    def convert(label: str, body: ConvertScope, request: Request, conn: Conn):
        def check():
            plan, problems = convert_plan(conn, label, body.rel_paths)
            if journal.token(plan) != body.token:
                raise journal.PlanError("the plan changed since you reviewed it; look again")
            if problems:
                raise journal.PlanError(
                    "nothing was converted: some files are not as scanned", problems
                )
            if not plan:
                raise journal.PlanError("there is nothing to convert")
            if journal.irreversible(plan) and body.confirm != label:
                raise journal.PlanError(
                    f"this deletes originals for good: type the folder label {label!r} to confirm"
                )
            return plan

        try:
            run_id = request.app.state.jobs.apply(
                conn, label, journal.APPLY, journal.CONVERT, check
            )
        except journal.PlanError as exc:
            raise conflict(str(exc), exc.problems) from exc
        return journal.progress(conn, run_id)

    def step_dict(m: journal.Move) -> dict:
        return {
            "rel_path": m.rel_path,
            "size": m.size,
            "destination": str(m.destination) if m.destination else None,
        }

    def guarded_preview(conn, label: str, plan, problems) -> dict:
        return {
            "token": journal.token(plan),
            "files": [step_dict(m) for m in plan],
            "irreversible": len(journal.irreversible(plan)),
            "bytes": sum(m.size for m in plan),
            "problems": [{"rel_path": r, "problem": p} for r, p in problems],
            "busy": journal.busy(conn, label),
        }

    def start_guarded(request, conn, label, scope, body, make_plan, nothing, after=None):
        def check():
            plan, problems = make_plan()
            if journal.token(plan) != body.token:
                raise journal.PlanError("the plan changed since you reviewed it; look again")
            if problems:
                raise journal.PlanError(
                    "nothing was changed: some files are not as listed", problems
                )
            if not plan:
                raise journal.PlanError(nothing)
            if journal.irreversible(plan) and body.confirm != label:
                raise journal.PlanError(
                    f"this deletes files for good: type the folder label {label!r} to confirm"
                )
            return plan

        try:
            run_id = request.app.state.jobs.apply(conn, label, journal.APPLY, scope, check, after)
        except journal.PlanError as exc:
            raise conflict(str(exc), exc.problems) from exc
        return journal.progress(conn, run_id)

    def unmatched_plan(conn, label: str, body: UnmatchedScope):
        folder = folder_or_404(label)
        root, gone = folder_root(folder), discarded.folder_root(settings, label)
        try:
            plan = journal.plan_unmatched(
                conn, label, root, gone, body.rel_paths, delete=body.delete, parts=parts_of(folder)
            )
        except journal.PlanError as exc:
            raise conflict(str(exc), exc.problems) from exc
        return plan, journal.preflight(plan, root, gone)

    @router.post("/folders/{label}/unmatched/preview")
    def unmatched_preview(label: str, body: UnmatchedScope, conn: Conn):
        return guarded_preview(conn, label, *unmatched_plan(conn, label, body))

    @router.post("/folders/{label}/unmatched", status_code=HTTPStatus.ACCEPTED)
    def unmatched_apply(label: str, body: UnmatchedScope, request: Request, conn: Conn):
        return start_guarded(
            request,
            conn,
            label,
            journal.SCOPE_UNMATCHED,
            body,
            lambda: unmatched_plan(conn, label, body),
            "there is nothing to move or delete",
        )

    def empty_plan(conn, label: str):
        folder = folder_or_404(label)
        gone = discarded.folder_root(settings, label)
        plan = journal.plan_empty(conn, label, gone, discarded.files_under(settings, label))
        return plan, journal.preflight(plan, folder_root(folder), gone)

    @router.post("/folders/{label}/discarded/empty/preview")
    def empty_preview(label: str, conn: Conn):
        return guarded_preview(conn, label, *empty_plan(conn, label))

    @router.post("/folders/{label}/discarded/empty", status_code=HTTPStatus.ACCEPTED)
    def empty_discarded(label: str, body: Guarded, request: Request, conn: Conn):
        root = discarded.folder_root(settings, label)
        return start_guarded(
            request,
            conn,
            label,
            journal.SCOPE_EMPTY,
            body,
            lambda: empty_plan(conn, label),
            "discarded/ is already empty",
            after=lambda: discarded.prune_empty(root),
        )

    @router.post("/folders/{label}/restore", status_code=HTTPStatus.ACCEPTED)
    def restore(label: str, body: RestoreScope, request: Request, conn: Conn):
        folder = folder_or_404(label)

        def check():
            plan = journal.plan_restore(
                conn, label, operation_ids=body.operation_ids, group_key=body.group_key
            )
            if not plan:
                raise journal.PlanError("there is nothing to restore")
            problems = journal.preflight(
                plan, folder_root(folder), discarded.folder_root(settings, label), journal.RESTORE
            )
            if problems:
                raise journal.PlanError("nothing was restored", problems)
            return plan

        try:
            run_id = request.app.state.jobs.apply(
                conn, label, journal.RESTORE, body.group_key or "", check
            )
        except journal.PlanError as exc:
            raise conflict(str(exc), exc.problems) from exc
        return journal.progress(conn, run_id)

    @router.get("/folders/{label}/run")
    def run_status(label: str, conn: Conn):
        folder_or_404(label)
        return journal.latest_run(conn, label)

    @router.get("/folders/{label}/games")
    def folder_games(label: str, conn: Conn):
        folder = folder_or_404(label)
        games = matching.game_rows(
            settings, conn, label, store.ranking_for(folder), produces(store.load(), folder, conn)
        )
        return [game_dict(g) for g in games]

    @router.put("/folders/{label}/keep")
    def keep(label: str, body: KeepChoice, conn: Conn):
        folder = folder_or_404(label)
        matching.set_keep(conn, label, body.group_key, body.rel_path)
        game = matching.find_game(
            settings,
            conn,
            label,
            store.ranking_for(folder),
            body.group_key,
            produces(store.load(), folder, conn),
        )
        if game is None:
            raise not_found("no such game")
        return game_dict(game)

    @router.put("/folders/{label}/leave")
    def leave(label: str, body: LeaveAlone, conn: Conn):
        folder = folder_or_404(label)
        matching.set_left_alone(conn, label, body.group_key, body.left)
        game = matching.find_game(
            settings,
            conn,
            label,
            store.ranking_for(folder),
            body.group_key,
            produces(store.load(), folder, conn),
        )
        if game is None:
            raise not_found("no such game")
        return game_dict(game)

    @router.put("/folders/{label}/ranking")
    def save_ranking(label: str, body: FolderRanking):
        folder_or_404(label)
        store.update(lambda lib: setattr(lib.folder(label), "ranking", body.ranking))
        return store.ranking_for(store.load().folder(label)).model_dump()

    # Conversion --------------------------------------------------------------------

    @router.get("/folders/{label}/conversion")
    def folder_conversion(label: str, conn: Conn):
        folder = folder_or_404(label)
        found = conversion_rows(store.load(), folder, conn)
        return {"counts": conversion.counts(found), "rows": [asdict(r) for r in found]}

    @router.put("/folders/{label}/conversion")
    def save_conversion(label: str, body: ConversionOptions):
        folder_or_404(label)
        store.update(
            lambda lib: setattr(lib.folder(label), "delete_originals", body.delete_originals)
        )
        return folder_info(store.load(), store.load().folder(label))

    # Unmatched content -------------------------------------------------------------

    @router.get("/folders/{label}/unmatched")
    def folder_unmatched(label: str, conn: Conn):
        folder = folder_or_404(label)
        lookups = store.load().lookups
        return unmatched.rows(
            conn, label, lookups.hasheous, lookups.screenscraper, parts_of(folder)
        )

    @router.put("/folders/{label}/assign")
    def assign(label: str, body: Assignment, conn: Conn):
        folder = folder_or_404(label)
        if body.game_name is not None:
            dat = registry.load_active(conn, store.load(), folder.platform)
            if dat is None or not any(g.name == body.game_name for g in dat.games):
                raise bad_request("That is not an entry of this platform's active DAT.")
            if scanner.latest_scan(conn, label) is None:
                raise bad_request("Scan the folder first.")
        known = conn.execute(
            "SELECT 1 FROM folder_file WHERE folder_label = ? AND rel_path = ?",
            (label, body.rel_path),
        ).fetchone()
        if not known:
            raise not_found("no such file in this folder's last scan")
        unmatched.assign(conn, label, body.rel_path, body.game_name)
        return {"rel_path": body.rel_path, "game_name": body.game_name}

    @router.get("/folders/{label}/dat-search")
    def dat_search(label: str, conn: Conn, q: str = ""):
        folder = folder_or_404(label)
        dat = registry.load_active(conn, store.load(), folder.platform)
        return [] if dat is None else unmatched.search(dat, q, settings.ui.dat_search_limit)

    # Scans -------------------------------------------------------------------------

    @router.post("/folders/{label}/scan", status_code=HTTPStatus.ACCEPTED)
    def start_scan(
        label: str,
        request: Request,
        conn: Conn,
        refresh_lookups: bool = False,
        full: bool = False,
    ):
        """A quick scan reads only new and changed files; `full` reads every file again."""
        folder_or_404(label)
        try:
            request.app.state.jobs.scan(conn, label, refresh_lookups, full)
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
            "lookups": library.lookups.model_dump(),
            "hasheous": {
                "site": settings.lookups.hasheous.site,
                "url": settings.lookups.hasheous.url,
                "sources": [s.label for s in settings.lookups.hasheous.sources.values()],
                "not_found_ttl_days": settings.lookups.hasheous.not_found_ttl_days,
            },
            "screenscraper": {
                "site": settings.lookups.screenscraper.site,
                "url": settings.lookups.screenscraper.url,
                # Credentials are never sent to the page: only whether they are set.
                "configured": screenscraper.credentials(settings) is not None,
                "credentials": screenscraper.credential_sources(settings),
                "environment": settings.lookups.screenscraper.environment.model_dump(),
                "min_interval_seconds": settings.lookups.screenscraper.min_interval_seconds,
                "not_found_ttl_days": settings.lookups.screenscraper.not_found_ttl_days,
                "platforms": sorted(
                    p for p, profile in platforms.items() if profile.screenscraper_id is not None
                ),
            },
            "fuzzy": settings.fuzzy.model_dump(),
            "effective_yaml": yaml.safe_dump(settings.model_dump(mode="json"), sort_keys=False),
            "library_file": str(settings.paths.library_path),
        }

    @router.put("/settings/lookups")
    def save_lookups(body: Lookups):
        if body.screenscraper and screenscraper.credentials(settings) is None:
            raise bad_request("ScreenScraper needs its developer credentials first")

        def change(library: Library) -> None:
            for name in ("hasheous", "screenscraper"):
                value = getattr(body, name)
                if value is not None:
                    setattr(library.lookups, name, value)

        store.update(change)
        return store.load().lookups.model_dump()

    @router.put("/settings/screenscraper-credentials")
    def save_screenscraper_credentials(body: ScreenScraperCredentials):
        screenscraper.store_credentials(settings, body.model_dump(exclude_none=True))
        # Only where each field is set: the values never leave the server.
        return screenscraper.credential_sources(settings)

    @router.delete("/settings/screenscraper-credentials")
    def remove_screenscraper_credentials():
        screenscraper.store_credentials(settings, dict.fromkeys(screenscraper.FIELDS))
        return screenscraper.credential_sources(settings)

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
                "downloads": [
                    {
                        "source": source_id,
                        "label": settings.dats.sources[source_id].label,
                        "identification_only": settings.dats.sources[source_id].identification_only,
                    }
                    for source_id in registry.downloads(pid)
                ],
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
    def dat_download(platform: str, conn: Conn, source: str = "libretro"):
        version_id = registry_call(lambda: registry.download(conn, platform, source))
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

    # Console keys (3DS decryption) ----------------------------------------------------
    # Only whether each file is there is ever returned: the keys never leave the server.

    @router.get("/keys")
    def keys():
        return decrypt.key_status(settings)

    @router.post("/keys/{kind}")
    async def add_key(kind: str, file: Annotated[UploadFile, File()]):
        data = await file.read(settings.decryption.max_upload_bytes + 1)
        try:
            decrypt.store_key(settings, kind, data)
        except decrypt.KeyFileError as exc:
            raise bad_request(str(exc)) from exc
        return decrypt.key_status(settings)

    @router.delete("/keys/{kind}")
    def remove_key(kind: str):
        try:
            decrypt.remove_key(settings, kind)
        except decrypt.KeyFileError as exc:
            raise not_found(str(exc)) from exc
        return decrypt.key_status(settings)

    return router
