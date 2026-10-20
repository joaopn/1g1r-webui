"""Reading DAT files: Logiqx XML (No-Intro, Redump) and clrmamepro text (libretro mirror).

Both parse to the same small model: a header and a list of games, each with its ROMs and
any parent/clone link the DAT carries.
"""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path


class DatError(ValueError):
    """The file is not a DAT this app can read."""


@dataclass(frozen=True)
class DatRom:
    name: str
    size: int | None
    crc: str | None
    md5: str | None
    sha1: str | None


@dataclass
class DatGame:
    name: str
    id: str | None = None
    cloneof: str | None = None
    cloneofid: str | None = None
    category: str | None = None
    description: str | None = None
    roms: list[DatRom] = field(default_factory=list)
    # A BIOS set (arcade): every game needs it.
    bios: bool = False
    # The product code printed on the game (Redump, libretro): "SLUS-20246", "CTR-P-AWAE".
    serial: str | None = None
    # Release year and publisher, where the DAT has them (FBNeo, some Logiqx DATs).
    year: str | None = None
    manufacturer: str | None = None


@dataclass
class DatHeader:
    name: str
    description: str | None = None
    version: str | None = None
    date: str | None = None
    author: str | None = None


@dataclass
class Dat:
    header: DatHeader
    games: list[DatGame]
    format: str

    @property
    def has_parent_clone(self) -> bool:
        return any(g.cloneof or g.cloneofid for g in self.games)


def _hex(value: str | None) -> str | None:
    return value.lower() if value else None


def _int(value: str | None) -> int | None:
    return int(value) if value and value.isdigit() else None


# Logiqx XML ------------------------------------------------------------------------


def _parse_xml(data: bytes) -> Dat:
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise DatError(f"not valid XML: {exc}") from exc
    if root.tag != "datafile":
        raise DatError(f"unexpected XML root <{root.tag}>")
    header_el = root.find("header")
    if header_el is None or not (header_el.findtext("name") or "").strip():
        raise DatError("the DAT has no <header><name>")
    header = DatHeader(
        name=header_el.findtext("name").strip(),
        description=header_el.findtext("description"),
        version=header_el.findtext("version"),
        date=header_el.findtext("date"),
        author=header_el.findtext("author"),
    )
    games = []
    for game_el in root.iter("game"):
        game = DatGame(
            name=game_el.get("name", ""),
            id=game_el.get("id"),
            cloneof=game_el.get("cloneof"),
            cloneofid=game_el.get("cloneofid"),
            category=game_el.findtext("category"),
            description=game_el.findtext("description"),
            bios=game_el.get("isbios") == "yes",
            serial=game_el.findtext("serial"),
            year=game_el.findtext("year"),
            manufacturer=game_el.findtext("manufacturer"),
        )
        for rom in game_el.iter("rom"):
            game.roms.append(
                DatRom(
                    name=rom.get("name", ""),
                    size=_int(rom.get("size")),
                    crc=_hex(rom.get("crc")),
                    md5=_hex(rom.get("md5")),
                    sha1=_hex(rom.get("sha1")),
                )
            )
        games.append(game)
    return Dat(header=header, games=games, format="logiqx")


# clrmamepro text -------------------------------------------------------------------

_TOKEN = re.compile(r'\s*(?:(\()|(\))|"((?:[^"\\]|\\.)*)"|([^\s()"]+))')


def _tokens(text: str):
    pos = 0
    while True:
        match = _TOKEN.match(text, pos)
        if not match or match.end() == pos:
            if text[pos:].strip():
                raise DatError(f"unreadable clrmamepro text near offset {pos}")
            return
        pos = match.end()
        opening, closing, quoted, bare = match.groups()
        if opening:
            yield "("
        elif closing:
            yield ")"
        else:
            yield ("str", quoted if quoted is not None else bare)


def _blocks(text: str) -> list[tuple[str, list]]:
    """Top-level `keyword ( key value ... )` blocks as (keyword, items) pairs.

    Items are (key, value) where value is a string or a nested item list.
    """
    stack: list[list] = [[]]
    pending_key: list[str | None] = [None]
    for token in _tokens(text):
        if token == "(":
            if pending_key[-1] is None:
                raise DatError("'(' without a preceding keyword")
            new: list = []
            stack[-1].append((pending_key[-1], new))
            pending_key[-1] = None
            stack.append(new)
            pending_key.append(None)
        elif token == ")":
            if len(stack) == 1:
                raise DatError("unbalanced ')'")
            stack.pop()
            pending_key.pop()
        else:
            value = token[1]
            if pending_key[-1] is None:
                pending_key[-1] = value
            else:
                stack[-1].append((pending_key[-1], value))
                pending_key[-1] = None
    if len(stack) != 1:
        raise DatError("unbalanced '('")
    return stack[0]


def _get(items: list, key: str) -> str | None:
    return next((v for k, v in items if k == key and isinstance(v, str)), None)


def _parse_clrmamepro(data: bytes) -> Dat:
    text = data.decode("utf-8", errors="replace")
    blocks = _blocks(text)
    header_items = next((v for k, v in blocks if k == "clrmamepro"), None)
    if header_items is None or not _get(header_items, "name"):
        raise DatError("the DAT has no clrmamepro ( name ... ) header")
    header = DatHeader(
        name=_get(header_items, "name"),
        description=_get(header_items, "description"),
        version=_get(header_items, "version"),
        date=_get(header_items, "date"),
        author=_get(header_items, "author"),
    )
    games = []
    for keyword, items in blocks:
        if keyword != "game" or isinstance(items, str):
            continue
        game = DatGame(
            name=_get(items, "name") or "",
            cloneof=_get(items, "cloneof"),
            category=_get(items, "category"),
            description=_get(items, "description"),
            serial=_get(items, "serial"),
            year=_get(items, "year"),
            manufacturer=_get(items, "manufacturer"),
        )
        for key, rom in items:
            if key == "rom" and not isinstance(rom, str):
                game.roms.append(
                    DatRom(
                        name=_get(rom, "name") or "",
                        size=_int(_get(rom, "size")),
                        crc=_hex(_get(rom, "crc")),
                        md5=_hex(_get(rom, "md5")),
                        sha1=_hex(_get(rom, "sha1")),
                    )
                )
        games.append(game)
    return Dat(header=header, games=games, format="clrmamepro")


_LEADING = b"\xef\xbb\xbf \t\r\n"


def parse_dat_bytes(data: bytes) -> Dat:
    stripped = data.lstrip(_LEADING)
    if stripped.startswith(b"<"):
        return _parse_xml(stripped)
    if stripped.startswith(b"clrmamepro"):
        return _parse_clrmamepro(stripped)
    raise DatError("not a Logiqx XML or clrmamepro DAT")


def parse_dat(path: Path) -> Dat:
    return parse_dat_bytes(path.read_bytes())


@cache
def parsed(path: Path, sha1: str) -> Dat:
    """A stored DAT, parsed once per process (its SHA1 names its content)."""
    return parse_dat(path)
