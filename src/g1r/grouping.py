"""Grouping a folder's identified files into games, each with its versions.

Sources, in order: the DAT's parent/clone links; Retool's clone lists; and (if enabled)
the DAT name with region, language, revision, pre-release, re-release and neutral tags
removed. Fuzzy matching never forms a group.
"""

import json
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path, PurePosixPath

from g1r import titles
from g1r.config import Settings
from g1r.dats import Dat, DatGame
from g1r.names import ParsedName, parse_name, parse_tosec

SOURCE_DAT = "dat-parent-clone"
SOURCE_RETOOL = "retool-clone-list"
SOURCE_NAME = "dat-name"
SOURCE_SINGLE = "single"
SOURCE_TITLE_ID = "title-id"
# Identifications of one ROM file: online lookups and name matches never look into an
# archive with several ROMs (scanner), so the file is one ROM whatever its DAT game lists.
SINGLE_FILE_METHODS = frozenset({"hasheous", "fuzzy"})


def is_disc_image(settings: Settings, rel_path: str) -> bool:
    """A disc format holding a whole disc (`platforms.disc_formats`: CHD, RVZ)."""
    suffix = PurePosixPath(rel_path).suffix.lower().lstrip(".")
    return suffix in settings.platforms.disc_formats


TOSEC_STYLE = "tosec"
NOINTRO_STYLE = "nointro"


@dataclass
class Version:
    rel_path: str
    game_name: str
    method: str
    parsed: ParsedName
    # The readable title (the DAT description for arcade sets, else the DAT name).
    title: str = ""
    # A clone in the DAT's parent/clone data; a BIOS set (arcade).
    clone: bool = False
    bios: bool = False
    # Title-ID platforms (Switch): titles.BASE, titles.UPDATE or titles.DLC, and the version
    # its content metadata gives (None: not read).
    role: str = ""
    title_version: int | None = None
    title_display: str | None = None
    # Its DAT lists fewer ROMs for this game than another DAT of the platform does (one disk
    # of a multi-disk game): never kept over a complete version.
    incomplete: bool = False
    # The DAT that identified it ("" for an online lookup or a title ID).
    dat_sha1: str = ""


@dataclass
class Group:
    key: str
    name: str
    source: str
    versions: list[Version] = field(default_factory=list)


@cache
def _retool_index(path: Path) -> dict[tuple[str, str], str]:
    """Retool clone list -> {(name type, lowercased search term): group}.

    Retool's "short" names keep every tag except region, language and ignored ones (such
    as revisions): "Tetris (Tengen)" is not "Tetris". Only short and full terms are used.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    index: dict[tuple[str, str], str] = {}
    for variant in data.get("variants", []):
        group = variant.get("group")
        for title in variant.get("titles", []):
            name_type = title.get("nameType", "short")
            if name_type in ("short", "full") and title.get("searchTerm"):
                index[(name_type, title["searchTerm"].lower())] = group
    return index


def retool_index(settings: Settings, dat: Dat) -> dict[tuple[str, str], str]:
    """Retool's clone list for the DAT: No-Intro's or Redump's, whichever exists."""
    base = dat.header.name.split(" (")[0]
    for family in settings.dats.families.values():
        path = settings.grouping.retool_clonelists_dir / f"{base} {family.clonelist_suffix}.json"
        if path.is_file():
            return _retool_index(path)
    return {}


def name_key(parsed: ParsedName, settings: Settings) -> str:
    neutral = [t.lower() for t in settings.names.neutral_tags]
    rereleases = [r.lower() for r in settings.names.rerelease_tags]

    def separates(tag: str) -> bool:
        lowered = tag.lower()
        if any(lowered == n or lowered.startswith(n + " ") for n in neutral):
            return False
        return not any(r in lowered for r in rereleases)

    kept = [t for t in parsed.other_tags if separates(t)]
    return " ".join([parsed.title] + [f"({t})" for t in kept])


def retool_group(retool, parsed: ParsedName, settings: Settings) -> str | None:
    full = retool.get(("full", parsed.name.lower()))
    return full if full is not None else retool.get(("short", name_key(parsed, settings).lower()))


def parent_names(dat: Dat) -> dict[str, str]:
    """Game name -> its parent's name, from cloneofid (by id) or cloneof (by name)."""
    by_id = {g.id: g.name for g in dat.games if g.id}
    parents = {}
    for game in dat.games:
        if game.cloneofid and game.cloneofid in by_id:
            parents[game.name] = by_id[game.cloneofid]
        elif game.cloneof:
            parents[game.name] = game.cloneof
    return parents


@dataclass
class SourceDat:
    """A DAT a folder's names come from, and how its names read."""

    sha1: str
    dat: Dat
    style: str = NOINTRO_STYLE


class DatSet:
    """The DATs of a platform, in its identification order. A name is read with the DAT
    that identified it (else the first that lists it); parent/clone links come from every
    DAT, the first DAT to give a game a parent winning."""

    def __init__(self, dats: list[SourceDat]):
        self.dats = dats
        self._games = [{g.name: g for g in d.dat.games} for d in dats]
        self.parents: dict[str, str] = {}
        for d in dats:
            for child, parent in parent_names(d.dat).items():
                self.parents.setdefault(child, parent)
        self.has_children = set(self.parents.values())
        # Game name -> the most ROMs any DAT lists for it.
        self.most_roms: dict[str, int] = {}
        for games in self._games:
            for name, game in games.items():
                self.most_roms[name] = max(self.most_roms.get(name, 0), len(game.roms))
        self._retool: dict[int, dict] = {}

    def source(self, game: str, dat_sha1: str = "") -> tuple[SourceDat | None, DatGame | None]:
        for d, games in zip(self.dats, self._games, strict=True):
            if d.sha1 == dat_sha1 and game in games:
                return d, games[game]
        for d, games in zip(self.dats, self._games, strict=True):
            if game in games:
                return d, games[game]
        return (self.dats[0] if self.dats else None), None

    def retool(self, settings: Settings, d: SourceDat | None) -> dict:
        if d is None:
            return {}
        if id(d) not in self._retool:
            self._retool[id(d)] = retool_index(settings, d.dat)
        return self._retool[id(d)]


def build_groups(
    settings: Settings,
    dats: "DatSet | Dat",
    identities: list[tuple],
    names_from: str = "name",
    name_style: str = NOINTRO_STYLE,
) -> list[Group]:
    """identities: (rel_path, game_name, method[, dat_sha1]). A file identified as several
    DAT games (identical data listed twice) is placed once, by its first game name.
    `names_from` "description": titles and name parsing use the DAT descriptions (arcade set
    names). One Dat (with `name_style`) stands for a set of one."""
    if isinstance(dats, Dat):
        dats = DatSet([SourceDat("", dats, name_style)])
    parents = dats.parents
    primary = dats.dats[0].style if dats.dats else NOINTRO_STYLE

    def title(game: str, known: DatGame | None) -> str:
        if names_from == "description" and known is not None and known.description:
            return known.description
        return game

    first_name: dict[str, tuple[str, str, str]] = {}
    for identity in sorted(identities):
        rel_path, game, method, *dat_sha1 = identity
        first_name.setdefault(rel_path, (game, method, (dat_sha1 or [""])[0] or ""))
    groups: dict[str, Group] = {}
    for rel_path, (game, method, dat_sha1) in first_name.items():
        source_dat, known = dats.source(game, dat_sha1)
        style = source_dat.style if source_dat else primary
        parsed = (
            parse_tosec(title(game, known), settings.names.tosec)
            if style == TOSEC_STYLE
            else parse_name(title(game, known), settings.names)
        )
        if game in parents:
            parent = parents[game]
            key, source, label = "dat:" + parent, SOURCE_DAT, title(parent, dats.source(parent)[1])
        elif game in dats.has_children:
            key, source, label = "dat:" + game, SOURCE_DAT, title(game, known)
        elif (
            label := retool_group(dats.retool(settings, source_dat), parsed, settings)
        ) is not None:
            key, source = "retool:" + label, SOURCE_RETOOL
        elif settings.grouping.infer_from_dat_names:
            label = name_key(parsed, settings)
            # Names in another DAT's convention never join this one's by their text.
            prefix = "" if style == primary else f"{style}:"
            key, source = f"name:{prefix}{label}", SOURCE_NAME
        else:
            key, source, label = "game:" + game, SOURCE_SINGLE, title(game, known)
        group = groups.setdefault(key, Group(key=key, name=label, source=source))
        group.versions.append(
            Version(
                rel_path,
                game,
                method,
                parsed,
                title(game, known),
                game in parents,
                known is not None and known.bios,
                incomplete=known is not None
                and (
                    len(known.roms) < dats.most_roms.get(game, 0)
                    # One file standing for a game its DAT lists as several (one disk).
                    # A disc image (CHD, RVZ) holds every track of its disc: it is whole.
                    or (
                        method in SINGLE_FILE_METHODS
                        and len(known.roms) > 1
                        and not is_disc_image(settings, rel_path)
                    )
                ),
                dat_sha1=dat_sha1,
            )
        )
    for group in groups.values():
        group.versions.sort(key=lambda v: v.game_name)
        if len(group.versions) == 1 and group.source == SOURCE_NAME:
            group.source = SOURCE_SINGLE
    return sorted(groups.values(), key=lambda g: g.name.lower())


# A title-ID game's key: this, then its base title ID.
TITLE_KEY_PREFIX = "tid:"


def build_title_groups(
    settings: Settings, identities: list[tuple[str, str, str, str]]
) -> list[Group]:
    """Title-ID platforms: one game per base title ID, holding its base files, update and
    DLC. The identity names carry the ID (titles.identity_name); the fourth item is the
    titledb file that named it ("" for none)."""
    config = settings.title_ids
    if config is None:
        return []
    groups: dict[str, Group] = {}
    names: dict[str, str] = {}
    based: set[str] = set()
    for rel_path, game, method, dat_sha1 in sorted(identities):
        title = titles.from_name(game, config)
        if title is None:
            continue
        role = title.role(config)
        app = titles.hex_id(title.app_id(config), config)
        key = TITLE_KEY_PREFIX + app
        # The game's name: its first base file's (by path), else its first file's.
        if key not in names or (role == titles.BASE and key not in based):
            names[key] = title.name
            if role == titles.BASE:
                based.add(key)
        group = groups.setdefault(key, Group(key=key, name="", source=SOURCE_TITLE_ID))
        parsed = parse_name(title.name, settings.names)
        group.versions.append(
            Version(
                rel_path,
                game,
                method,
                parsed,
                game,
                role=role,
                title_version=title.version,
                title_display=title.display,
                dat_sha1=dat_sha1 or "",
            )
        )
    for key, group in groups.items():
        group.name = names[key]
        group.versions.sort(key=lambda v: (v.role != titles.BASE, v.game_name))
    return sorted(groups.values(), key=lambda g: g.name.lower())
