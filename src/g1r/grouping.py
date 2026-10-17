"""Grouping a folder's identified files into games, each with its versions.

Sources, in order: the DAT's parent/clone links; Retool's clone lists; and (if enabled)
the DAT name with region, language, revision, pre-release, re-release and neutral tags
removed. Fuzzy matching never forms a group.
"""

import json
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from g1r.config import Settings
from g1r.dats import Dat
from g1r.names import ParsedName, parse_name

SOURCE_DAT = "dat-parent-clone"
SOURCE_RETOOL = "retool-clone-list"
SOURCE_NAME = "dat-name"
SOURCE_SINGLE = "single"


@dataclass
class Version:
    rel_path: str
    game_name: str
    method: str
    parsed: ParsedName


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


def build_groups(
    settings: Settings, dat: Dat, identities: list[tuple[str, str, str]]
) -> list[Group]:
    """identities: (rel_path, game_name, method). A file identified as several DAT games
    (identical data listed twice) is placed once, by its first game name."""
    parents = parent_names(dat)
    retool = retool_index(settings, dat)
    first_name: dict[str, tuple[str, str]] = {}
    for rel_path, game, method in sorted(identities):
        first_name.setdefault(rel_path, (game, method))
    groups: dict[str, Group] = {}
    for rel_path, (game, method) in first_name.items():
        parsed = parse_name(game, settings.names)
        if game in parents:
            key, source, label = "dat:" + parents[game], SOURCE_DAT, parents[game]
        elif any(child_parent == game for child_parent in parents.values()):
            key, source, label = "dat:" + game, SOURCE_DAT, game
        elif (label := retool_group(retool, parsed, settings)) is not None:
            key, source = "retool:" + label, SOURCE_RETOOL
        elif settings.grouping.infer_from_dat_names:
            label = name_key(parsed, settings)
            key, source = "name:" + label, SOURCE_NAME
        else:
            key, source, label = "game:" + game, SOURCE_SINGLE, game
        group = groups.setdefault(key, Group(key=key, name=label, source=source))
        group.versions.append(Version(rel_path, game, method, parsed))
    for group in groups.values():
        group.versions.sort(key=lambda v: v.game_name)
        if len(group.versions) == 1 and group.source == SOURCE_NAME:
            group.source = SOURCE_SINGLE
    return sorted(groups.values(), key=lambda g: g.name.lower())
