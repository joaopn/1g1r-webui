"""Switch names and details from titledb: one JSON file per eShop country and language.

Each file lists the shop's entries by eShop ID, each with the title ID it sells. A
downloaded file is kept as a small Logiqx DAT: one game per title ID (its `id`), named as
the shop names it, with publisher, release date and languages, and no ROMs. It is one
entry of the platform's order; the first active file listing a title ID names the file
read with that ID. Nothing here identifies a file: the title ID read inside it does.
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime
from xml.sax.saxutils import escape, quoteattr

from g1r.config import TitleDbConfig
from g1r.dats import Dat


class TitleDbError(ValueError):
    """A titledb file could not be used; the message is shown to the user."""


def entry_id(config: TitleDbConfig, file: str) -> str:
    """A region file as an entry of the platform's order: "titledb:US.en"."""
    return config.entry_prefix + file


def file_of(config: TitleDbConfig, entry: str) -> str | None:
    """The region file an order entry names, or None for any other entry."""
    return entry[len(config.entry_prefix) :] if entry.startswith(config.entry_prefix) else None


def label(config: TitleDbConfig, entry: str) -> str:
    return f"{config.short_label} {file_of(config, entry)}"


def files_from_languages(config: TitleDbConfig, data: bytes) -> list[str]:
    """Every region file named by languages.json (country -> its languages)."""
    try:
        countries = json.loads(data)
    except ValueError as exc:
        raise TitleDbError(f"languages.json is not JSON: {exc}") from exc
    if not isinstance(countries, dict):
        raise TitleDbError("languages.json is not a country -> languages map")
    pattern = re.compile(config.file_pattern)
    found = {
        f"{country}.{language}"
        for country, languages in countries.items()
        if isinstance(languages, list)
        for language in languages
        if isinstance(language, str)
    }
    return sorted(f for f in found if pattern.match(f))


def _name(config: TitleDbConfig, name: str) -> str:
    for old, new in config.name_replacements.items():
        name = name.replace(old, new)
    return " ".join(name.split())


def _release(config: TitleDbConfig, value) -> str | None:
    if value is None:
        return None
    try:
        return datetime.strptime(str(value), config.release_format).strftime(config.release_display)
    except ValueError:
        return None


def to_dat(config: TitleDbConfig, file: str, data: bytes, version: str) -> tuple[bytes, int]:
    """The region file as a Logiqx DAT and how many title IDs it lists. Entries without a
    title ID (bundles, shop pages) are left out; a title ID listed twice keeps its first
    named entry."""
    try:
        entries = json.loads(data)
    except ValueError as exc:
        raise TitleDbError(f"{file}: not JSON: {exc}") from exc
    if not isinstance(entries, dict):
        raise TitleDbError(f"{file}: not a titledb region file")
    titles: dict[str, dict] = {}
    for entry in entries.values():
        if not isinstance(entry, dict):
            continue
        title_id, name = entry.get("id"), entry.get("name")
        if not isinstance(title_id, str) or not isinstance(name, str) or not name.strip():
            continue
        titles.setdefault(title_id.upper(), entry)
    if not titles:
        raise TitleDbError(f"{file}: no entry with a title ID")
    header = f"{config.short_label} {file}"
    lines = [
        "<?xml version='1.0' encoding='utf-8'?>",
        "<datafile>",
        "<header>",
        f"<name>{escape(header)}</name>",
        f"<description>{escape(header)} as of {escape(version)}</description>",
        f"<version>{escape(version)}</version>",
        f"<author>{escape(config.label)}</author>",
        "</header>",
    ]
    for title_id, entry in sorted(titles.items()):
        name = _name(config, entry["name"])
        category = config.demo_category if entry.get("isDemo") else config.game_category
        lines.append(f"<game name={quoteattr(name)} id={quoteattr(title_id)}>")
        lines.append(f"<description>{escape(name)}</description>")
        lines.append(f"<category>{escape(category)}</category>")
        publisher = entry.get("publisher")
        if isinstance(publisher, str) and publisher.strip():
            lines.append(f"<manufacturer>{escape(publisher.strip())}</manufacturer>")
        release = _release(config, entry.get("releaseDate"))
        if release:
            lines.append(f"<year>{escape(release)}</year>")
        languages = entry.get("languages")
        if isinstance(languages, list):
            codes = list(dict.fromkeys(c for c in languages if isinstance(c, str)))
            if codes:
                lines.append(f"<languages>{escape(','.join(codes))}</languages>")
        lines.append("</game>")
    lines.append("</datafile>")
    return "\n".join(lines).encode("utf-8"), len(titles)


@dataclass(frozen=True)
class Title:
    """What a titledb file says about one title ID."""

    name: str
    publisher: str | None
    release: str | None
    languages: tuple[str, ...]
    sha1: str


_indexes: dict[str, dict[str, Title]] = {}


def index(sha1: str, dat: Dat) -> dict[str, Title]:
    """A titledb DAT by title ID (built once per process: its SHA1 names its content)."""
    if sha1 not in _indexes:
        _indexes[sha1] = _index(sha1, dat)
    return _indexes[sha1]


def _index(sha1: str, dat: Dat) -> dict[str, Title]:
    return {
        game.id.upper(): Title(
            game.name,
            game.manufacturer,
            game.year,
            tuple(c for c in (game.languages or "").split(",") if c),
            sha1,
        )
        for game in dat.games
        if game.id
    }


def lookup(ordered: list[dict[str, Title]], *title_ids: str) -> Title | None:
    """The first file in the order listing the first of these title IDs any file lists."""
    for title_id in title_ids:
        found = next((titles[title_id] for titles in ordered if title_id in titles), None)
        if found is not None:
            return found
    return None
