"""The JSON API the web app talks to. Every route is read-only towards ROM folders."""

import re
import sqlite3
from collections.abc import Callable
from dataclasses import asdict
from http import HTTPStatus
from typing import Annotated

import yaml
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from g1r import (
    automatch,
    conversion,
    dashboard,
    decrypt,
    discarded,
    filecache,
    hasheous,
    igir,
    journal,
    matching,
    mounts,
    notifications,
    scanner,
    statistics,
    unmatched,
)
from g1r.config import RANKING_CRITERIA, RankingConfig, Settings
from g1r.dat_registry import DatRegistry, RegistryError, name_style
from g1r.hasheous import SERVICE as HASHEOUS
from g1r.library import FolderEntry, Library, LibraryStore
from g1r.ranking import LABELS as RANKING_LABELS

LOOKUP_LABELS = {HASHEOUS: "Hasheous"}

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


class SetAsideScope(BaseModel):
    # Flagged or unsupported files to move to discarded/<label>/manual/.
    rel_paths: list[str]
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


class Targets(BaseModel):
    targets: dict[str, str]


class Ignored(BaseModel):
    patterns: list[str]


class JobLimit(BaseModel):
    # None: back to the configured default.
    value: int | None = Field(default=None, gt=0)


class IgirThreads(BaseModel):
    # None: igir's own.
    value: int | None = Field(default=None, gt=0)


class ActiveVersion(BaseModel):
    version_id: int


class Pinned(BaseModel):
    pinned: bool
    # The source whose active DAT is pinned; empty: the platform's first DAT.
    source: str = ""


class DatOrder(BaseModel):
    # None: back to the global order (a platform's), or to the default (the global one).
    order: list[str] | None
    off: list[str] = []


class FolderRanking(BaseModel):
    ranking: RankingConfig | None


# Serialisers -------------------------------------------------------------------------


def row_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def game_dict(game: matching.GameRow, dats: dict[str, dict] | None = None) -> dict:
    """`dats`: sha1 -> what to say about that DAT (`dat_names`)."""
    dats = dats or {}
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
                # The DAT that identified it: its source and version.
                "dat": dats.get(row.version.dat_sha1),
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
                # "incomplete": its DAT lists fewer ROMs for the game than another DAT.
                "notes": row.notes + (["incomplete"] if row.version.incomplete else []),
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

    def waiting_of(library: Library, folder: FolderEntry, conn) -> frozenset[str]:
        """Files a conversion is proposed for: neither versions nor unmatched until converted
        (maintainer, 2026-10-21: conversion first, then 1G1R)."""
        return frozenset(conversion.waiting(conversion_rows(library, folder, conn)))

    def produces(
        library: Library, folder: FolderEntry, conn, waiting: frozenset[str] | None = None
    ) -> matching.FolderView:
        """The folder's platform as the 1G1R table sees it; names read as its active DAT's."""
        dats = tuple(
            (v["sha1"], name_style(v))
            for v in registry.active_versions(conn, library, folder.platform)
        )
        target = settings.platforms.targets[store.target_for(library, folder.platform)]
        profile = platforms[folder.platform]
        return matching.FolderView(
            target.produces,
            parts_of(folder),
            profile.names_from,
            profile.title_ids,
            dats,
            waiting_of(library, folder, conn) if waiting is None else waiting,
        )

    def dat_names(conn) -> dict[str, dict]:
        """Every stored DAT by sha1: its source, short and full, and its version."""
        found = {}
        for row in conn.execute("SELECT sha1, source, version, header_name FROM dat_version"):
            source = settings.dats.sources.get(row["source"])
            found[row["sha1"]] = {
                "source": row["source"],
                "label": source.short_label if source else row["source"],
                "source_label": source.label if source else row["source"],
                "version": row["version"],
                "header_name": row["header_name"],
            }
        return found

    def entry_label(entry: str) -> str:
        source = settings.dats.sources.get(entry)
        return source.label if source else LOOKUP_LABELS.get(entry, entry)

    def own_order(library: Library, platform: str) -> bool:
        dats = library.dats.get(platform)
        return dats is not None and dats.order is not None

    def dat_order(conn, library: Library, platform: str) -> list[dict]:
        """The platform's identification order: each source's active DAT, and the online
        lookups, with whether each is on."""
        return [
            {
                "id": e.id,
                "label": entry_label(e.id),
                "on": e.on,
                "lookup": e.lookup,
                "dat": row_dict(e.version),
                "pinned": bool(
                    e.version is not None and library.dats[platform].active[e.id].pinned
                ),
            }
            for e in registry.entries(conn, library, platform)
        ]

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

    def title_ids(platform: str) -> bool:
        """The platform identifies by title ID, so a scan needs no DAT."""
        return platform in platforms and platforms[platform].title_ids

    @router.get("/folders")
    def list_folders(conn: Conn):
        library = store.load()
        result = []
        for folder in library.folders:
            ranking = store.ranking_for(folder)
            converting = conversion_rows(library, folder, conn)
            waiting = frozenset(conversion.waiting(converting))
            games = matching.game_rows(
                settings, conn, folder.label, ranking, produces(library, folder, conn, waiting)
            )
            table = matching.table(settings, conn, folder.label, ranking, games=games)
            info = folder_info(library, folder)
            scan = scanner.latest_scan(conn, folder.label)
            dat = registry.active_version(conn, library, folder.platform)
            parts = parts_of(folder)
            summary = scanner.folder_summary(conn, folder.label, parts, waiting)
            last_scan = scanner.latest_scan(conn, folder.label, scanner.IDENTIFY)
            needed = dashboard.needs(
                scan, last_scan, dat, journal.last_conversion_end(conn, folder.label)
            )
            result.append(
                {
                    **info,
                    # The latest run of either kind (Check files or Scan), and the latest Scan.
                    "scan": row_dict(scan),
                    "last_scan": row_dict(last_scan),
                    "dat": row_dict(dat),
                    "summary": summary,
                    "dat_download": default_download(folder.platform) if dat is None else None,
                    "needs_dat": dat is None and not title_ids(folder.platform),
                    "needs_scan": needed is not None,
                    # Which button: "check" (Check files) or "identify" (Scan).
                    "needs": needed,
                    "counts": table.counts,
                    "reclaim_bytes": table.reclaim_bytes,
                    "conversion": conversion.counts(converting),
                    "progress": dashboard.progress(
                        scanner.rom_paths(conn, folder.label),
                        games,
                        converting,
                        # Not scanned yet counts too: a Scan is how it gets matched.
                        (
                            r["rel_path"]
                            for r in [
                                *scanner.unmatched_files(conn, folder.label, parts, waiting),
                                *scanner.unscanned_files(conn, folder.label, parts, waiting),
                            ]
                        ),
                    ),
                    "discarded": discarded.totals(settings, folder.label),
                    "converting": journal.running_conversion(conn, folder.label),
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
                        hasheous_offered=not library.lookups.hasheous,
                    ),
                }
            )
        return result

    def statistics_dats(conn, library: Library, folder: FolderEntry) -> dict[str, sqlite3.Row]:
        """The folder's platform's local DATs by source (switched-off ones too)."""
        return {
            e.id: e.version
            for e in registry.entries(conn, library, folder.platform)
            if e.version is not None
        }

    def statistics_games(folder: FolderEntry, version: sqlite3.Row) -> statistics.DatGames:
        return statistics.dat_games(
            settings,
            version["sha1"],
            registry.load(version),
            name_style(version),
            platforms[folder.platform].names_from,
        )

    def statistics_folder(conn, library: Library, folder: FolderEntry) -> dict:
        """The folder's row, as kept, or computed now when never computed. `stale`: its
        files, identities or DATs changed since."""
        dats = statistics_dats(conn, library, folder)
        current = statistics.fingerprint(
            settings, conn, folder.label, [v["sha1"] for v in dats.values()]
        )
        kept = statistics.cached(conn, statistics.KIND_FOLDER, folder.label)
        if kept is None:
            have = statistics.identified(settings, conn, folder.label)
            summary = scanner.folder_summary(conn, folder.label, parts_of(folder))
            cells = {}
            for source, version in dats.items():
                covered, total, _ = statistics.coverage(statistics_games(folder, version), have)
                cells[source] = {"covered": covered, "total": total, "dat": row_dict(version)}
            value = {
                "roms": summary["roms"],
                "identified": summary["identified"],
                "coverage": cells,
            }
            kept = statistics.keep(conn, statistics.KIND_FOLDER, folder.label, current, value)
        return kept.value | {
            "label": folder.label,
            "platform": folder.platform,
            "platform_short": platforms[folder.platform].short,
            "computed_at": kept.computed_at,
            "stale": kept.fingerprint != current,
        }

    def statistics_features(conn, version: dict) -> dict:
        """What kind of data a DAT carries (kept by its SHA1: a DAT file never changes)."""
        sha1 = version["sha1"]
        kept = statistics.cached(conn, statistics.KIND_DAT, sha1)
        if kept is None:
            features = statistics.dat_features(registry.load(version))
            kept = statistics.keep(conn, statistics.KIND_DAT, sha1, sha1, features)
        return kept.value

    @router.get("/statistics")
    def get_statistics(conn: Conn):
        library = store.load()
        folders = [
            statistics_folder(conn, library, folder)
            for folder in library.folders
            if not folder.hidden and folder.platform in platforms
        ]
        local: dict[str, dict[str, dict]] = {}
        for folder in folders:
            for source, cell in folder["coverage"].items():
                local.setdefault(source, {})[cell["dat"]["sha1"]] = cell["dat"]
        sources = [
            {"id": sid, "label": source.label, "short_label": source.short_label}
            for sid, source in settings.dats.sources.items()
        ]
        dat_info = []
        for sid, source in settings.dats.sources.items():
            versions = list(local.get(sid, {}).values())
            features = [statistics_features(conn, v) for v in versions]
            dat_info.append(
                {
                    "id": sid,
                    "label": source.label,
                    "dats": len(versions),
                    "identification_only": source.identification_only,
                    "checksums": sorted({c for f in features for c in f["checksums"]}),
                    "categories": sorted({c for f in features for c in f["categories"]}),
                    "parent_clone": any(f["parent_clone"] for f in features),
                    "bios": any(f["bios"] for f in features),
                    "serials": any(f["serials"] for f in features),
                    "years": any(f["years"] for f in features),
                    "publishers": any(f["publishers"] for f in features),
                }
            )
        return {
            "sources": sources,
            "folders": folders,
            "dat_info": dat_info,
            "rules": settings.statistics.model_dump(),
        }

    @router.post("/statistics/refresh")
    def refresh_statistics(conn: Conn):
        statistics.forget(conn)
        return get_statistics(conn)

    @router.get("/statistics/{label}/{source}/missing")
    def get_missing(label: str, source: str, conn: Conn):
        folder = folder_or_404(label)
        library = store.load()
        dats = statistics_dats(conn, library, folder)
        if source not in dats:
            raise not_found(f"{label!r} has no {source!r} DAT")
        version = dats[source]
        current = statistics.fingerprint(
            settings, conn, folder.label, [v["sha1"] for v in dats.values()]
        )
        key = statistics.missing_key(label, source)
        kept = statistics.cached(conn, statistics.KIND_MISSING, key)
        if kept is None or kept.fingerprint != current:
            games = statistics_games(folder, version)
            have = statistics.identified(settings, conn, folder.label)
            covered, total, missing = statistics.coverage(games, have)
            value = {
                "dat": row_dict(version),
                "covered": covered,
                "total": total,
                "rows": statistics.missing_rows(settings, games, missing),
            }
            kept = statistics.keep(conn, statistics.KIND_MISSING, key, current, value)
        return kept.value

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
        statistics.forget(conn, label)
        igir.cache_path(settings, label).unlink(missing_ok=True)

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
        waiting = waiting_of(library, folder, conn)
        return {
            **folder_info(library, folder),
            "dat": row_dict(registry.active_version(conn, library, folder.platform)),
            "dat_order": dat_order(conn, library, folder.platform),
            "dat_order_own": own_order(library, folder.platform),
            "scan": row_dict(scanner.latest_scan(conn, label)),
            "last_scan": row_dict(scanner.latest_scan(conn, label, scanner.IDENTIFY)),
            "summary": scanner.folder_summary(conn, label, parts_of(folder), waiting),
            "unmatched": [
                dict(r) for r in scanner.unmatched_files(conn, label, parts_of(folder), waiting)
            ],
            # ROM files a conversion is proposed for: identified once converted.
            "convert_first": [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM folder_file WHERE folder_label = ? AND place = 'folder' "
                    "AND kind IN ('rom', 'archive') ORDER BY rel_path",
                    (label,),
                )
                if r["rel_path"] in waiting
            ],
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

    def set_aside_plan(conn, label: str, body: SetAsideScope):
        folder = folder_or_404(label)
        root, gone = folder_root(folder), discarded.folder_root(settings, label)
        profile = platforms[folder.platform]
        eligible = {
            r.rel_path
            for r in conversion_rows(store.load(), folder, conn)
            if r.status == conversion.FLAGGED
        }
        eligible |= {
            f["rel_path"]
            for f in scanner.unsupported_files(conn, label, profile.rom_extensions, profile.romsets)
        }
        eligible |= journal.failed_conversions(conn, label)
        try:
            plan = journal.plan_set_aside(conn, label, root, gone, body.rel_paths, eligible)
        except journal.PlanError as exc:
            raise conflict(str(exc), exc.problems) from exc
        return plan, journal.preflight(plan, root, gone)

    @router.post("/folders/{label}/set-aside/preview")
    def set_aside_preview(label: str, body: SetAsideScope, conn: Conn):
        return guarded_preview(conn, label, *set_aside_plan(conn, label, body))

    @router.post("/folders/{label}/set-aside", status_code=HTTPStatus.ACCEPTED)
    def set_aside_apply(label: str, body: SetAsideScope, request: Request, conn: Conn):
        return start_guarded(
            request,
            conn,
            label,
            journal.SCOPE_SET_ASIDE,
            body,
            lambda: set_aside_plan(conn, label, body),
            "there is nothing to move",
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

    @router.post("/folders/{label}/convert/stop", status_code=HTTPStatus.ACCEPTED)
    def stop_conversion(label: str, request: Request, conn: Conn):
        """No file starts; the ones under way are cut off and their output deleted."""
        folder_or_404(label)
        if not request.app.state.jobs.stop_conversion(conn, label):
            raise conflict("no conversion is running in this folder")
        return journal.latest_run(conn, label)

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
        names = dat_names(conn)
        return [game_dict(g, names) for g in games]

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
        return game_dict(game, dat_names(conn))

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
        return game_dict(game, dat_names(conn))

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
            conn, label, lookups.hasheous, parts_of(folder), waiting_of(store.load(), folder, conn)
        )

    @router.put("/folders/{label}/assign")
    def assign(label: str, body: Assignment, conn: Conn):
        folder = folder_or_404(label)
        dat_sha1 = ""
        if body.game_name is not None:
            listing = [
                version["sha1"]
                for version, dat in registry.load_all(conn, store.load(), folder.platform)
                if any(g.name == body.game_name for g in dat.games)
            ]
            if not listing:
                raise bad_request("That is not an entry of this platform's DATs.")
            if scanner.latest_scan(conn, label) is None:
                raise bad_request("Scan the folder first.")
            dat_sha1 = listing[0]
        known = conn.execute(
            "SELECT 1 FROM folder_file WHERE folder_label = ? AND rel_path = ?",
            (label, body.rel_path),
        ).fetchone()
        if not known:
            raise not_found("no such file in this folder's last scan")
        unmatched.assign(conn, label, body.rel_path, body.game_name, dat_sha1)
        return {"rel_path": body.rel_path, "game_name": body.game_name}

    @router.get("/folders/{label}/dat-search")
    def dat_search(label: str, conn: Conn, q: str = ""):
        folder = folder_or_404(label)
        dats = [d for _, d in registry.load_all(conn, store.load(), folder.platform)]
        return unmatched.search(dats, q, settings.ui.dat_search_limit)

    # Scans -------------------------------------------------------------------------

    @router.post("/folders/{label}/scan", status_code=HTTPStatus.ACCEPTED)
    def start_scan(
        label: str,
        request: Request,
        conn: Conn,
        refresh_lookups: bool = False,
        full: bool = False,
    ):
        """Check the files, then identify those with nothing left to convert. A quick scan
        reads only new and changed files; `full` reads every file again."""
        folder_or_404(label)
        try:
            request.app.state.jobs.scan(conn, label, refresh_lookups, full)
        except scanner.ScanError as exc:
            raise HTTPException(status_code=HTTPStatus.CONFLICT, detail=str(exc)) from exc
        return row_dict(scanner.latest_scan(conn, label))

    @router.post("/folders/{label}/check", status_code=HTTPStatus.ACCEPTED)
    def start_check(label: str, request: Request, conn: Conn):
        """Check files: list the folder and read what conversion needs, hashing nothing."""
        folder_or_404(label)
        try:
            request.app.state.jobs.scan(conn, label, kind=scanner.CHECK)
        except scanner.ScanError as exc:
            raise HTTPException(status_code=HTTPStatus.CONFLICT, detail=str(exc)) from exc
        return row_dict(scanner.latest_scan(conn, label))

    @router.get("/folders/{label}/scan")
    def scan_status(label: str, conn: Conn):
        folder_or_404(label)
        return row_dict(scanner.latest_scan(conn, label))

    # Notifications -----------------------------------------------------------------

    @router.get("/notifications")
    def list_notifications(conn: Conn):
        return notifications.feed(conn, settings.ui.notifications.limit)

    @router.delete("/notifications", status_code=HTTPStatus.NO_CONTENT)
    def clear_notifications(conn: Conn):
        notifications.clear(conn)

    @router.delete("/notifications/{item_id}", status_code=HTTPStatus.NO_CONTENT)
    def dismiss_notification(item_id: str, conn: Conn):
        if notifications.parse_id(item_id) is None:
            raise not_found("no such notification")
        notifications.clear(conn, item_id)

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
                # Named like the platform's DAT: taken. The others: only a name a DAT lists.
                "sources": [
                    s.label
                    for s in settings.lookups.hasheous.sources.values()
                    if s.trust == hasheous.TRUST_SOURCE
                ],
                "other_sources": [
                    s.label
                    for s in settings.lookups.hasheous.sources.values()
                    if s.trust != hasheous.TRUST_SOURCE
                ],
                "not_found_ttl_days": settings.lookups.hasheous.not_found_ttl_days,
            },
            "fuzzy": settings.fuzzy.model_dump(),
            "parallel_scans": {
                "value": store.parallel_scans(library),
                "default": settings.jobs.scan_workers,
                "max": settings.jobs.max_scan_workers,
            },
            "parallel_conversions": {
                "value": store.parallel_conversions(library),
                "default": settings.jobs.conversion_workers,
                "max": settings.jobs.max_conversion_workers,
            },
            "igir_threads": {
                "value": store.igir_threads(library),
                "default_readers": settings.igir.default_reader_threads,
                "default_pool": settings.igir.default_pool_threads,
                "max": settings.igir.max_threads,
            },
            "effective_yaml": yaml.safe_dump(settings.model_dump(mode="json"), sort_keys=False),
            "library_file": str(settings.paths.library_path),
        }

    @router.put("/settings/lookups")
    def save_lookups(body: Lookups):
        def change(library: Library) -> None:
            if body.hasheous is not None:
                library.lookups.hasheous = body.hasheous

        store.update(change)
        return store.load().lookups.model_dump()

    @router.put("/settings/targets")
    def save_targets(body: Targets):
        def change(library: Library) -> None:
            for platform, target in body.targets.items():
                if platform not in platforms or target not in platforms[platform].targets:
                    raise bad_request(f"{target!r} is not a target for {platform!r}")
                library.platform_targets[platform] = target

        store.update(change)
        return get_settings()

    @router.put("/settings/parallel-scans")
    def save_parallel_scans(body: JobLimit, request: Request):
        if body.value is not None and body.value > settings.jobs.max_scan_workers:
            raise bad_request(f"at most {settings.jobs.max_scan_workers} scans at a time")
        store.update(lambda lib: setattr(lib, "parallel_scans", body.value))
        request.app.state.jobs.limit_changed()
        return get_settings()

    @router.put("/settings/parallel-conversions")
    def save_parallel_conversions(body: JobLimit):
        if body.value is not None and body.value > settings.jobs.max_conversion_workers:
            raise bad_request(
                f"at most {settings.jobs.max_conversion_workers} conversions at a time"
            )
        store.update(lambda lib: setattr(lib, "parallel_conversions", body.value))
        return get_settings()

    @router.put("/settings/igir-threads")
    def save_igir_threads(body: IgirThreads):
        if body.value is not None and body.value > settings.igir.max_threads:
            raise bad_request(f"at most {settings.igir.max_threads} igir threads")
        store.update(lambda lib: setattr(lib, "igir_threads", body.value))
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
                "order": dat_order(conn, library, pid),
                "own_order": own_order(library, pid),
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

    @router.delete("/dats/sources/{source}")
    def dat_remove_source(source: str, conn: Conn):
        """Every DAT of one source, on every platform, is removed (files included)."""
        if conn.execute("SELECT 1 FROM scan WHERE status = 'running'").fetchone():
            raise HTTPException(
                status_code=HTTPStatus.CONFLICT,
                detail="a scan is running: remove DATs once it has finished",
            )
        removed, from_platforms = registry_call(lambda: registry.remove_source(conn, source))
        return {"versions": removed, "platforms": from_platforms}

    @router.put("/dats/{platform}/active")
    def dat_activate(platform: str, body: ActiveVersion, conn: Conn):
        registry_call(lambda: registry.activate(conn, platform, body.version_id))
        return {"ok": True}

    @router.put("/dats/{platform}/pin")
    def dat_pin(platform: str, body: Pinned, conn: Conn):
        source = body.source
        if not source:
            first = registry.active_version(conn, store.load(), platform)
            source = first["source"] if first is not None else ""
        registry_call(lambda: registry.set_pinned(platform, source, body.pinned))
        return {"ok": True}

    @router.put("/dats/{platform}/order")
    def dat_set_order(platform: str, body: DatOrder, conn: Conn):
        """The order the platform's sources and online lookups identify files in, for
        every set of the platform; the next scan uses it."""
        if platform not in platforms:
            raise not_found("no such platform")
        registry_call(lambda: registry.set_order(platform, body.order, body.off))
        return dat_order(conn, store.load(), platform)

    def global_order(library: Library) -> dict:
        off = set(library.dat_off)
        return {
            "own": library.dat_order is not None,
            "entries": [
                {
                    "id": entry,
                    "label": entry_label(entry),
                    "on": entry not in off,
                    "lookup": entry in LOOKUP_LABELS,
                }
                for entry in registry.global_order(library)
            ],
        }

    @router.get("/dat-order")
    def get_global_order():
        """The order every platform without its own follows."""
        return global_order(store.load())

    @router.put("/dat-order")
    def set_global_order(body: DatOrder):
        registry_call(lambda: registry.set_global_order(body.order, body.off))
        return global_order(store.load())

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
