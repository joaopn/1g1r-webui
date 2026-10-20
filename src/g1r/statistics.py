"""Statistics: how much of each local DAT a folder covers, counting games only.

A game is a group, formed the way the Matching table groups (DAT parent/clone, Retool clone
lists, names), over every game the DAT lists. Only games count: a DAT entry in a category
other than a game one, tagged as a demo, pre-release, homebrew, pirate, program, hack or
BIOS, or (TOSEC) a pre-release or a modified or bad dump, is left out, and a group whose
entries are all left out is not counted. A game is covered when one of its remaining
versions is in the folder; a left-out version never covers one.

A file identified by another DAT covers a game of this one when its DAT game's ROM checksums
cover every ROM of that game, or when this DAT lists the same game name.

The figures are kept in the statistics_cache table and recomputed on request (the page's
Refresh); a folder's fingerprint tells whether its files, identities or DATs changed since.
"""

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, field

from g1r import grouping, matching
from g1r.config import Settings
from g1r.dats import Dat, DatGame
from g1r.grouping import TOSEC_STYLE, DatSet, SourceDat
from g1r.journal import PLACE_FOLDER
from g1r.names import parse_name, parse_tosec, tags


@dataclass(frozen=True)
class GameInfo:
    """What the DAT says about one of its entries."""

    name: str
    year: str | None
    publisher: str | None
    regions: tuple[str, ...]
    languages: tuple[str, ...]
    serial: str | None
    # The name's other tags ("Unl", "Virtual Console"), its ROM names' included.
    notes: tuple[str, ...] = ()


@dataclass
class DatGames:
    """The games of one DAT, as statistics count them."""

    # Group key -> its label and the names of its counted entries.
    labels: dict[str, str] = field(default_factory=dict)
    members: dict[str, list[str]] = field(default_factory=dict)
    group_of: dict[str, str] = field(default_factory=dict)
    info: dict[str, GameInfo] = field(default_factory=dict)
    # ROM checksum key -> counted entries with such a ROM; entry -> its ROMs' keys.
    by_key: dict[tuple, set[str]] = field(default_factory=dict)
    rom_keys: dict[str, list[set[tuple]]] = field(default_factory=dict)


def rom_keys(game: DatGame) -> list[set[tuple]]:
    """Each ROM's checksum keys: SHA1, MD5 and CRC with size, whichever the DAT gives."""
    found = []
    for rom in game.roms:
        keys = set()
        if rom.sha1:
            keys.add(("sha1", rom.sha1))
        if rom.md5:
            keys.add(("md5", rom.md5))
        if rom.crc and rom.size is not None:
            keys.add(("crc", rom.crc, rom.size))
        found.append(keys)
    return found


def _excluded_tag(text: str, words: list[str]) -> bool:
    for _, tag in tags(text):
        for part in tag.split(","):
            lowered = part.strip().lower()
            if any(lowered == w or lowered.startswith(w + " ") for w in words):
                return True
    return False


def is_game(settings: Settings, entries: list[DatGame], style: str) -> bool:
    """Whether a DAT name is a game: every entry listed under it passes the filters."""
    config = settings.statistics
    words = [w.lower() for w in config.excluded_tags]
    categories = {c.lower() for c in config.categories}
    flags = {f.lower() for f in config.tosec_excluded_flags}
    for game in entries:
        if game.bios:
            return False
        if game.category and game.category.strip().lower() not in categories:
            return False
        if style == TOSEC_STYLE:
            parsed = parse_tosec(game.name, settings.names.tosec)
            if parsed.prerelease or flags & set(parsed.dump_flags):
                return False
            continue
        texts = [game.name, game.description or "", *(r.name for r in game.roms)]
        if any(_excluded_tag(t, words) for t in texts):
            return False
    return True


def _info(settings: Settings, game: DatGame, style: str, names_from: str) -> GameInfo:
    shown = game.description if names_from == "description" and game.description else game.name
    year, publisher = game.year, game.manufacturer
    if style == TOSEC_STYLE:
        parsed = parse_tosec(shown, settings.names.tosec)
        # TOSEC names: "Title (year)(publisher)...".
        parens = [t for kind, t in tags(shown) if kind == "paren"]
        if parens and re.match(settings.statistics.tosec_year_pattern, parens[0]):
            year = year or parens[0]
            if len(parens) > 1:
                publisher = publisher or parens[1]
        notes = [t for t in parsed.other_tags if t not in (year, publisher)]
    else:
        parsed = parse_name(shown, settings.names)
        notes = list(parsed.other_tags)
        # The libretro mirror tags some entries on the ROM name only.
        for rom in game.roms:
            notes += parse_name(rom.name, settings.names).other_tags
    labels = settings.statistics.note_labels
    # Spelled-out notes first, so sorting by them keeps those games together.
    notes = [labels[n] for n in notes if n in labels] + [n for n in notes if n not in labels]
    notes = list(dict.fromkeys(notes))
    return GameInfo(
        shown, year, publisher, parsed.regions, parsed.languages, game.serial, tuple(notes)
    )


_cache: dict[tuple, DatGames] = {}


def dat_games(settings: Settings, sha1: str, dat: Dat, style: str, names_from: str) -> DatGames:
    """The DAT's counted games (cached per DAT, name style and naming)."""
    key = (id(settings), sha1, style, names_from)
    if key in _cache:
        return _cache[key]
    by_name: dict[str, list[DatGame]] = {}
    for game in dat.games:
        by_name.setdefault(game.name, []).append(game)
    kept = [n for n, entries in by_name.items() if is_game(settings, entries, style)]
    result = DatGames()
    dats = DatSet([SourceDat(sha1, dat, style)])
    groups = grouping.build_groups(
        settings, dats, [(n, n, "dat", sha1) for n in kept], names_from, style
    )
    for group in groups:
        result.labels[group.key] = group.name
        result.members[group.key] = [v.game_name for v in group.versions]
        for version in group.versions:
            result.group_of[version.game_name] = group.key
    for name in kept:
        first = by_name[name][0]
        result.info[name] = _info(settings, first, style, names_from)
        keys = rom_keys(first)
        result.rom_keys[name] = keys
        for rom in keys:
            for k in rom:
                result.by_key.setdefault(k, set()).add(name)
    _cache[key] = result
    return result


@dataclass
class Identified:
    """A folder's identified files, as the names and ROM checksums they stand for."""

    names: set[str] = field(default_factory=set)
    keys: set[tuple] = field(default_factory=set)


def identified(settings: Settings, conn: sqlite3.Connection, label: str) -> Identified:
    """The DAT games of the files in the folder (discarded ones left out). One disk of a
    multi-ROM game named by a single-file method (Hasheous, fuzzy) stands for nothing."""
    found = Identified()
    dats: dict[str, dict[str, DatGame]] = {}
    rows = conn.execute(
        "SELECT i.rel_path, i.game_name, i.method, i.dat_sha1 FROM identity i JOIN folder_file f "
        "USING (folder_label, rel_path) WHERE i.folder_label = ? AND f.place = ?",
        (label, PLACE_FOLDER),
    )
    for row in rows:
        sha1 = row["dat_sha1"]
        if sha1 and sha1 not in dats:
            dat = matching.load_dat(settings, conn, sha1)
            dats[sha1] = {g.name: g for g in dat.games} if dat else {}
        game = dats.get(sha1, {}).get(row["game_name"])
        if (
            game is not None
            and row["method"] in grouping.SINGLE_FILE_METHODS
            and len(game.roms) > 1
            and not grouping.is_disc_image(settings, row["rel_path"])
        ):
            continue
        found.names.add(row["game_name"])
        if game is not None:
            for rom in rom_keys(game):
                found.keys |= rom
    return found


def covered_names(games: DatGames, have: Identified) -> set[str]:
    """The DAT's counted entries the folder has."""
    found = {n for n in have.names if n in games.group_of}
    candidates = set()
    for k in have.keys:
        candidates |= games.by_key.get(k, set())
    for name in candidates - found:
        roms = games.rom_keys[name]
        if roms and all(rom & have.keys for rom in roms):
            found.add(name)
    return found


def coverage(games: DatGames, have: Identified) -> tuple[int, int, list[str]]:
    """(covered games, counted games, keys of the missing ones)."""
    covered = {games.group_of[n] for n in covered_names(games, have)}
    missing = [k for k in games.members if k not in covered]
    return len(covered), len(games.members), missing


def _joined(values) -> str | None:
    seen: list[str] = []
    for v in values:
        if v and v not in seen:
            seen.append(v)
    return ", ".join(seen) or None


def missing_rows(settings: Settings, games: DatGames, keys: list[str]) -> list[dict]:
    """One row per missing game: the distinct values of its versions, joined. `marked`: a
    note is a spelled-out one (statistics.note_labels: Unlicensed)."""
    labelled = set(settings.statistics.note_labels.values())
    rows = []
    for key in keys:
        infos = [games.info[n] for n in games.members[key]]
        notes = [n for i in infos for n in i.notes]
        notes = [n for n in notes if n in labelled] + [n for n in notes if n not in labelled]
        rows.append(
            {
                "key": key,
                "name": games.labels[key],
                "versions": len(infos),
                "years": _joined(i.year for i in infos),
                "publishers": _joined(i.publisher for i in infos),
                "regions": _joined(r for i in infos for r in i.regions),
                "languages": _joined(lang for i in infos for lang in i.languages),
                "serials": _joined(i.serial for i in infos),
                "notes": _joined(notes),
                "marked": any(n in labelled for n in notes),
                "entries": [i.name for i in infos],
            }
        )
    return sorted(rows, key=lambda r: r["name"].lower())


def dat_features(dat: Dat) -> dict:
    """What kind of data a DAT carries."""
    games = dat.games
    checksums = [
        name
        for name, present in (
            ("CRC32", any(r.crc for g in games for r in g.roms)),
            ("MD5", any(r.md5 for g in games for r in g.roms)),
            ("SHA1", any(r.sha1 for g in games for r in g.roms)),
        )
        if present
    ]
    return {
        "games": len({g.name for g in games}),
        "checksums": checksums,
        "categories": sorted({g.category for g in games if g.category}),
        "parent_clone": any(g.cloneof or g.cloneofid for g in games),
        "bios": any(g.bios for g in games),
        "serials": any(g.serial for g in games),
        "years": any(g.year for g in games),
        "publishers": any(g.manufacturer for g in games),
    }


KIND_FOLDER = "folder"
KIND_MISSING = "missing"
KIND_DAT = "dat"


def fingerprint(settings: Settings, conn: sqlite3.Connection, label: str, sha1s: list[str]) -> str:
    """What a folder's figures depend on: its files, their identities, its DATs and the
    counting rules."""
    digest = hashlib.sha1(usedforsecurity=False)
    digest.update(json.dumps([sha1s, settings.statistics.model_dump()]).encode())
    for table, columns in (
        ("folder_file", "rel_path, kind, place"),
        ("identity", "rel_path, game_name, method, dat_sha1"),
    ):
        rows = conn.execute(
            f"SELECT {columns} FROM {table} WHERE folder_label = ? ORDER BY {columns}", (label,)
        )
        for row in rows:
            digest.update(json.dumps(list(row)).encode())
    return digest.hexdigest()


@dataclass(frozen=True)
class Cached:
    fingerprint: str
    computed_at: str
    value: dict


def cached(conn: sqlite3.Connection, kind: str, key: str) -> Cached | None:
    row = conn.execute(
        "SELECT fingerprint, computed_at, value FROM statistics_cache WHERE kind = ? AND key = ?",
        (kind, key),
    ).fetchone()
    if row is None:
        return None
    return Cached(row["fingerprint"], row["computed_at"], json.loads(row["value"]))


def keep(conn: sqlite3.Connection, kind: str, key: str, fingerprint: str, value: dict) -> Cached:
    conn.execute(
        "INSERT OR REPLACE INTO statistics_cache (kind, key, fingerprint, value) "
        "VALUES (?, ?, ?, ?)",
        (kind, key, fingerprint, json.dumps(value)),
    )
    return cached(conn, kind, key)


def missing_key(label: str, source: str) -> str:
    return json.dumps([label, source])


def forget(conn: sqlite3.Connection, label: str | None = None) -> None:
    """Drop a folder's figures, or (no label) everything kept."""
    if label is None:
        conn.execute("DELETE FROM statistics_cache")
        return
    conn.execute("DELETE FROM statistics_cache WHERE kind = ? AND key = ?", (KIND_FOLDER, label))
    conn.execute(
        "DELETE FROM statistics_cache WHERE kind = ? AND json_extract(key, '$[0]') = ?",
        (KIND_MISSING, label),
    )
