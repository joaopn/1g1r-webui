"""TOSEC: one pack of thousands of DATs, merged here into one DAT per platform.

tosecdev.org publishes the complete pack (a zip) on a release page; there is no download
per system. Each TOSEC DAT covers one system, category and format ("Commodore C64 - Games -
Arcade - [D64]"), so a platform takes every DAT whose name starts with one of its prefixes
(`platforms.profiles.<id>.tosec_prefixes`) and they become a single DAT the app keeps as one
version, like any other. A game named alike in two of them (the same release as D64 and as
TAP) is listed once per DAT, its name followed by the format, so every name stays unique.
"""

import io
import re
import urllib.parse
import zipfile
from collections.abc import Callable
from pathlib import PurePosixPath
from xml.sax.saxutils import escape, quoteattr

from g1r.config import DatSourceConfig
from g1r.dats import DatError, parse_dat_bytes

Fetch = Callable[[str], bytes]
# The format a TOSEC DAT covers, at the end of its name: "... - [D64]".
_FORMAT = re.compile(r"\[(?P<format>[^\[\]]+)\]\s*$")


class TosecError(ValueError):
    """The pack could not be found or used; the message is shown to the user."""


def latest_pack_url(fetch: Fetch, source: DatSourceConfig) -> str:
    """The newest release page on the index, then the complete pack on that page."""
    if not (source.index_url and source.release_pattern and source.pack_pattern):
        raise TosecError("the TOSEC source has no index_url, release_pattern or pack_pattern")
    index = fetch(source.index_url).decode("utf-8", errors="replace")
    releases = re.findall(source.release_pattern, index)
    if not releases:
        raise TosecError(f"no TOSEC release found on {source.index_url}")
    # Release pages end with their date (YYYY-MM-DD); the newest sorts last.
    newest = max(set(releases), key=lambda link: link[-len("YYYY-MM-DD") :])
    release = urllib.parse.urljoin(source.index_url, newest)
    page = fetch(release).decode("utf-8", errors="replace")
    packs = re.findall(source.pack_pattern, page)
    if not packs:
        raise TosecError(f"no complete DAT pack found on {release}")
    return urllib.parse.urljoin(release, packs[0].replace("&amp;", "&"))


def is_pack(archive: zipfile.ZipFile, member_dir: str) -> bool:
    return any(name.startswith(member_dir) for name in archive.namelist())


def platform_dats(
    archive: zipfile.ZipFile, member_dir: str, prefixes: list[str], limit: int
) -> list[tuple[str, bytes]]:
    """The pack's DATs for one platform (by file name, without reading the others)."""
    found, total = [], 0
    for info in archive.infolist():
        name = PurePosixPath(info.filename)
        if not info.filename.startswith(member_dir) or name.suffix.lower() != ".dat":
            continue
        if not any(name.name.startswith(p) for p in prefixes):
            continue
        total += info.file_size
        if total > limit:
            raise TosecError("the platform's TOSEC DATs unpack to more than dats.max_upload_bytes")
        found.append((name.name, archive.read(info)))
    return found


def merge(dats: list[tuple[str, bytes]], header_name: str) -> bytes:
    """One Logiqx DAT holding every game of `dats`, under `header_name`."""
    if not dats:
        raise TosecError("the pack holds no DAT for this platform")
    parsed = []
    for filename, data in sorted(dats):
        try:
            parsed.append(parse_dat_bytes(data))
        except DatError as exc:
            raise TosecError(f"{filename}: {exc}") from exc
    counts: dict[str, int] = {}
    for dat in parsed:
        for game in dat.games:
            counts[game.name] = counts.get(game.name, 0) + 1
    versions = sorted({d.header.version for d in parsed if d.header.version})
    lines = [
        "<?xml version='1.0' encoding='utf-8'?>",
        "<datafile>",
        "<header>",
        f"<name>{escape(header_name)}</name>",
        f"<description>{escape(header_name)}: {len(parsed)} TOSEC DATs merged</description>",
        f"<version>{escape(versions[-1] if versions else '')}</version>",
        "<author>TOSEC</author>",
        "</header>",
    ]
    seen: set[str] = set()
    for dat in parsed:
        fmt = _FORMAT.search(dat.header.name)
        for game in dat.games:
            name = game.name
            label = fmt["format"] if fmt else dat.header.name
            if counts[name] > 1:
                name = f"{game.name} {{{label}}}"
            copy = 1
            while name in seen:
                copy += 1
                name = f"{game.name} {{{label} {copy}}}"
            seen.add(name)
            lines.append(f"<game name={quoteattr(name)}>")
            lines.append(f"<description>{escape(game.description or game.name)}</description>")
            for rom in game.roms:
                attrs = {"name": rom.name, "size": rom.size, "crc": rom.crc, "md5": rom.md5}
                attrs["sha1"] = rom.sha1
                text = " ".join(f"{k}={quoteattr(str(v))}" for k, v in attrs.items() if v)
                lines.append(f"<rom {text}/>")
            lines.append("</game>")
    lines.append("</datafile>")
    return "\n".join(lines).encode("utf-8")


def open_pack(data: bytes) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise TosecError("the TOSEC pack is not a valid zip file") from exc
