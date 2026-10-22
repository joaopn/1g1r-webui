"""The conversion part: what each file of a folder would become under its platform's target.

Proposals only: nothing here touches a file. Every proposal is lossless by construction
(wrap a ROM in a zip, or take it out of one; a disc into one file; a byte-swapped ROM into
its native order) and names the check that would prove it.
"""

import fnmatch
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from g1r import cards, cso, decrypt, discs
from g1r.config import PLAIN, Settings, TargetConfig

REASON_ORIGINALS = "originals"

DONE = "done"
ACCEPTED = "accepted"
WRAP = "wrap"
UNWRAP = "unwrap"
MAKE_CHD = "make chd"
MAKE_RVZ = "make rvz"
# A ROM in a swapped byte order (N64 .v64) rewritten in the native one.
BYTESWAP = "byteswap"
# An encrypted 3DS card image decrypted with the user's own keys.
DECRYPT = "decrypt"
# What a card image's header says, as the Conversion table explains it.
NOTE_TEXT = {
    cards.ENCRYPTED: (
        "encrypted: standalone Azahar plays it only with keys dumped from your console, the "
        "libretro core not at all; the DAT lists decrypted images, so it is not matched by "
        "checksum (Unmatched suggests the entries with its product code)"
    ),
    cards.TRIMMED: "trimmed (the card's empty padding was cut off): it runs the same",
}
# A track file a cue sheet's conversion takes along.
PART = "part"
FLAGGED = "flagged"
STATUSES = (WRAP, UNWRAP, MAKE_CHD, MAKE_RVZ, BYTESWAP, DECRYPT, FLAGGED, PART, ACCEPTED, DONE)
CONVERTING = (WRAP, UNWRAP, MAKE_CHD, MAKE_RVZ, BYTESWAP, DECRYPT)
# The only archive the app writes; other targets are listed but never produced here.
ZIP = "zip"
ZIP_SUFFIX = f".{ZIP}"
CHD = "chd"
# platforms.profiles.<id>.iso_mode for platforms whose ISOs are DVDs.
ISO_MODE_DVD = "dvd"

# How a conversion is carried out (converter.Converter).
RECIPE_WRAP = "wrap"
RECIPE_UNWRAP = "unwrap"
# chdman createcd/createdvd from a cue sheet or ISO in the folder.
RECIPE_DISC = "disc"
# The same from a cue sheet or ISO inside an archive, extracted to a work directory first.
RECIPE_ARCHIVE_DISC = "archive-disc"
# The ROM (bare, or an archive's one ROM member) rewritten in the native byte order.
RECIPE_BYTESWAP = "byteswap"
# A bare card image decrypted (decrypt.decrypt_cci), proved by a DAT entry's SHA1.
RECIPE_DECRYPT = "decrypt"


@dataclass
class ConversionRow:
    rel_path: str
    size: int
    container: str
    members: list[dict] = field(default_factory=list)
    status: str = DONE
    output: str | None = None
    originals_to: str | None = None
    reversible: bool = True
    verify: str | None = None
    note: str = ""
    recipe: str | None = None
    # A cue sheet's track files (paths in the folder), converted and moved with it.
    parts: list[str] = field(default_factory=list)
    # createcd or createdvd, for a disc recipe.
    disc_mode: str | None = None
    # The word length whose bytes are reversed, and the archive member read, for a byteswap.
    word_bytes: int | None = None
    source_member: dict | None = None
    # The ROM's name inside the output zip, when the output is a zip made from another name.
    output_member: str | None = None
    # Decrypt: the card image format (settings.card_images), whose hashes prove the output.
    card_image: str | None = None


def waiting(rows: list[ConversionRow]) -> set[str]:
    """The files a conversion is proposed for (and the tracks it takes along): they are
    identified and ranked once converted (maintainer, 2026-10-21: conversion first)."""
    return {
        rel
        for r in rows
        if r.status in CONVERTING or r.status == PART
        for rel in (r.rel_path, *r.parts)
    }


def container_of(rel_path: str, kind: str, disc_formats=()) -> str:
    suffix = PurePosixPath(rel_path).suffix.lower().lstrip(".")
    if kind == "archive":
        return suffix
    return suffix if suffix in disc_formats else PLAIN


def originals_path(settings: Settings, label: str, rel_path: str) -> str:
    return str(PurePosixPath(settings.paths.discarded_root, label, REASON_ORIGINALS, rel_path))


def originals_path_under(originals_to: str, rel_path: str, part: str) -> str:
    """Where a conversion's other original (a cue sheet's track) goes, beside `originals_to`
    (the main file's place there), keeping the folder's structure."""
    base = PurePosixPath(originals_to)
    for _ in PurePosixPath(rel_path).parts:
        base = base.parent
    return str(base / part)


def _ext(name: str) -> str:
    return PurePosixPath(name).suffix.lower().lstrip(".")


def rows(
    settings: Settings,
    conn: sqlite3.Connection,
    label: str,
    platform: str,
    target: TargetConfig,
    *,
    delete_originals: bool,
    root: Path | None = None,
) -> list[ConversionRow]:
    """`root`: the folder on disk, where loose cue sheets are read (None: not available)."""
    profile = settings.platforms.profiles[platform]
    rom_extensions = {e.lower() for e in profile.rom_extensions}
    part_extensions = {e.lower() for e in profile.part_extensions}
    keep_extensions = {e.lower() for e in profile.keep_extensions}
    disc_formats = {e.lower() for e in settings.platforms.disc_formats}
    to_disc = target.produces in disc_formats
    files = conn.execute(
        "SELECT rel_path, size, kind FROM folder_file WHERE folder_label = ? "
        "AND kind IN ('rom', 'archive') AND place = 'folder' ORDER BY rel_path",
        (label,),
    ).fetchall()
    members: dict[str, list[dict]] = {}
    for m in conn.execute(
        "SELECT rel_path, member, size, crc32 FROM archive_member WHERE folder_label = ? "
        "ORDER BY rel_path, member",
        (label,),
    ):
        members.setdefault(m["rel_path"], []).append(
            {"name": m["member"], "size": m["size"], "crc32": m["crc32"]}
        )
    problems = dict(
        conn.execute(
            "SELECT rel_path, message FROM archive_problem WHERE folder_label = ?", (label,)
        ).fetchall()
    )
    # Discarded rows count too: an output may not take the name of a file in discarded/.
    existing = {
        r[0].lower()
        for r in conn.execute("SELECT rel_path FROM folder_file WHERE folder_label = ?", (label,))
    }
    held = {
        r[0].lower()
        for r in conn.execute(
            "SELECT rel_path FROM folder_file WHERE folder_label = ? AND place = 'discarded'",
            (label,),
        )
    }
    swapped = dict(
        conn.execute(
            "SELECT rel_path, word_bytes FROM byte_order WHERE folder_label = ?", (label,)
        ).fetchall()
    )
    byte_order = settings.byte_orders.get(platform)
    file_notes: dict[str, list[str]] = {}
    for rel, note in conn.execute(
        "SELECT rel_path, note FROM file_note WHERE folder_label = ? ORDER BY note", (label,)
    ):
        file_notes.setdefault(rel, []).append(note)
    locked = {
        rel: (bool(seed), program_id)
        for rel, seed, program_id in conn.execute(
            "SELECT rel_path, seed, program_id FROM card_info "
            "WHERE folder_label = ? AND encrypted = 1",
            (label,),
        )
    }
    seeds = decrypt.seed_ids(settings) if locked else None
    sheets, taken = _cue_sheets(files, root) if to_disc else ({}, {})
    patterns = [p.lower() for p in settings.platforms.lossy_patterns]

    def lossy(name: str) -> bool:
        return any(fnmatch.fnmatchcase(name.lower(), p) for p in patterns)

    def is_rom(name: str) -> bool:
        return _ext(name) in rom_extensions

    planned: set[str] = set()
    result = []
    for f in files:
        rel = f["rel_path"]
        row = ConversionRow(
            rel, f["size"], container_of(rel, f["kind"], disc_formats), members.get(rel, [])
        )
        roms = [m for m in row.members if is_rom(m["name"])]
        ext = _ext(rel)
        if rel in problems:
            row.status, row.note = FLAGGED, problems[rel]
        elif lossy(PurePosixPath(rel).name):
            row.status = FLAGGED
            row.note = "already stripped of data (scrubbed or trimmed): never converted further"
        elif rel in locked and row.container == PLAIN:
            _decrypt(settings, label, row, profile, locked[rel], seeds, None, delete_originals)
        elif (
            rel in locked
            and len(roms) == 1
            and not _cannot_decrypt(settings, profile, locked[rel], seeds)
        ):
            # Unpacked and decrypted in one go; without what decryption needs, only unpacked.
            _decrypt(settings, label, row, profile, locked[rel], seeds, roms[0], delete_originals)
        elif kept := keep_as_is(rel, f["kind"], roms, keep_extensions):
            if f["kind"] == "archive" and len(roms) == 1:
                # Never converted, but unpacked: emulators read the bare image.
                _unwrap(row, roms[0], len(row.members) - len(roms))
                _originals(settings, label, row, delete_originals)
            elif f["kind"] == "archive":
                # One game's discs belong together (maintainer, 2026-10-21).
                row.status = ACCEPTED
                row.note = f"{len(roms)} ROM files kept together in one archive"
            else:
                row.status, row.note = ACCEPTED, f".{kept} is kept as it is: it is never converted"
        elif to_disc and f["kind"] == "rom" and ext in discs.SHEETS:
            sheet = sheets.get(rel)
            if isinstance(sheet, str):
                row.status, row.note = FLAGGED, sheet
            else:
                row.parts = sheet
                row.members = [{"name": PurePosixPath(p).name} for p in sheet]
                _disc(settings, label, row, RECIPE_DISC, ext, profile, target, delete_originals)
        elif to_disc and f["kind"] == "rom" and ext in profile.part_extensions:
            if rel in taken:
                row.status, row.note = PART, f"converted with {taken[rel]}"
            else:
                row.status, row.note = FLAGGED, "a track no cue sheet in the folder refers to"
        elif to_disc and f["kind"] == "rom" and ext in (*discs.IMAGES, cso.CSO):
            _disc(settings, label, row, RECIPE_DISC, ext, profile, target, delete_originals)
        elif to_disc and f["kind"] == "archive" and _disc_inside(roms, part_extensions):
            _disc(
                settings,
                label,
                row,
                RECIPE_ARCHIVE_DISC,
                _disc_inside(roms, part_extensions),
                profile,
                target,
                delete_originals,
            )
        elif profile.romsets:
            # Arcade: an archive is a romset, kept whole; a loose chip file is not a game.
            if f["kind"] != "archive":
                row.status, row.note = FLAGGED, "a loose chip ROM: arcade games are romset zips"
            elif row.container == target.produces:
                row.status = DONE
            elif row.container in target.accepts:
                row.status, row.note = ACCEPTED, f"{row.container} is accepted as it is"
            else:
                row.status, row.note = (
                    FLAGGED,
                    f"a {row.container} romset: the app makes no romsets",
                )
        elif row.container not in (PLAIN, *disc_formats) and not roms:
            row.status = FLAGGED
            row.note = f"no {profile.name} ROM inside ({', '.join(profile.rom_extensions)})"
        elif row.container not in (PLAIN, *disc_formats) and len(roms) > 1:
            # The disks of one game belong together: kept as they are, never unpacked.
            together = f"{len(roms)} ROM files kept together in one archive"
            if row.container == target.produces:
                row.status, row.note = DONE, together
            elif row.container in target.accepts:
                row.status, row.note = ACCEPTED, together
            else:
                row.status = FLAGGED
                row.note = f"{together}: only single-ROM archives are converted"
        elif rel in swapped and byte_order is not None:
            _byteswap(
                settings, label, target, row, roms, swapped[rel], byte_order, delete_originals
            )
        elif row.container == target.produces:
            row.status = DONE
        elif row.container in target.accepts:
            row.status, row.note = ACCEPTED, f"{row.container} is accepted as it is"
        else:
            _propose(settings, label, target, row, roms, delete_originals)
        if row.output:
            if row.output.lower() in existing | planned:
                row.status = FLAGGED
                if row.output.lower() in held:
                    row.note = (
                        f"{row.output} is the name of a file in discarded/, which a restore "
                        "would need back; empty discarded/ to convert this"
                    )
                else:
                    row.note = f"{row.output} already exists or is another file's output"
                row.output = row.verify = row.recipe = row.originals_to = None
                row.parts = []
            else:
                planned.add(row.output.lower())
        notes = file_notes.get(rel, [])
        if row.status == DECRYPT:
            notes = [n for n in notes if n != cards.ENCRYPTED]
        if notes:
            if cards.ENCRYPTED in notes and row.status in (DONE, ACCEPTED):
                row.status = FLAGGED
            row.note = "; ".join([*(NOTE_TEXT.get(n, n) for n in notes), *filter(None, [row.note])])
        result.append(row)
    # A track whose cue sheet could not be converted is not taken along after all.
    converting = {p for r in result if r.status in CONVERTING for p in r.parts}
    for row in result:
        if row.status == PART and row.rel_path not in converting:
            row.status, row.note = FLAGGED, "its cue sheet cannot be converted (see the cue)"
    return result


def keep_as_is(rel_path: str, kind: str, roms: list[dict], keep: set[str]) -> str | None:
    """The keep-as-is format (`keep_extensions`) of a bare file, or of an archive whose ROMs
    are all in one, else None."""
    if kind != "archive":
        return _ext(rel_path) if _ext(rel_path) in keep else None
    found = {_ext(m["name"]) for m in roms}
    return found.pop() if len(found) == 1 and found <= keep else None


def _cue_sheets(files, root: Path | None) -> tuple[dict, dict]:
    """Loose cue sheets -> their track files (folder paths), or why they cannot be used;
    and each track -> the cue sheet taking it along."""
    present = {f["rel_path"] for f in files}
    sheets: dict[str, list[str] | str] = {}
    taken: dict[str, str] = {}
    for f in files:
        rel = f["rel_path"]
        if f["kind"] != "rom" or _ext(rel) not in discs.SHEETS:
            continue
        if root is None:
            sheets[rel] = "the folder is not available to read the cue sheet"
            continue
        try:
            names = discs.read_sheet(root / rel)
        except discs.DiscError as exc:
            sheets[rel] = str(exc)
            continue
        parent = PurePosixPath(rel).parent
        tracks = [str(parent / PurePosixPath(n.replace("\\", "/"))) for n in names]
        missing = [t for t in tracks if t not in present]
        shared = [t for t in tracks if t in taken]
        if not tracks:
            sheets[rel] = "the cue sheet names no track files"
        elif missing:
            sheets[rel] = (
                f"the cue sheet refers to {PurePosixPath(missing[0]).name}, which is missing"
            )
        elif shared:
            sheets[rel] = f"{PurePosixPath(shared[0]).name} belongs to {taken[shared[0]]} too"
        else:
            sheets[rel] = tracks
            taken.update(dict.fromkeys(tracks, rel))
    return sheets, taken


def _disc_inside(roms: list[dict], parts: set[str]) -> str | None:
    """An archive holding one disc: a cue sheet or .gdi with its tracks (files of the
    platform's part extensions), or a single image."""
    kinds = Counter(_ext(m["name"]) for m in roms)
    sheets = [k for k in kinds if k in discs.SHEETS]
    if (
        len(sheets) == 1
        and kinds[sheets[0]] == 1
        and set(kinds) <= parts | {sheets[0]}
        and len(roms) > 1
    ):
        return sheets[0]
    if len(roms) == 1 and _ext(roms[0]["name"]) in discs.IMAGES:
        return _ext(roms[0]["name"])
    return None


def _disc(settings, label, row, recipe, source, profile, target, delete_originals) -> None:
    parent = PurePosixPath(row.rel_path).parent
    produces = target.produces
    row.recipe = recipe
    if produces == discs.RVZ:
        row.status, row.disc_mode = MAKE_RVZ, discs.RVZ
        row.verify = "dolphin-tool verify: the RVZ's disc SHA1 must equal the image's"
    else:
        row.status = MAKE_CHD
        dvd = source in (*discs.IMAGES, cso.CSO) and profile.iso_mode == ISO_MODE_DVD
        row.disc_mode = discs.CREATEDVD if dvd else discs.CREATECD
        row.verify = "chdman verify, then the data extracted back must equal the originals (SHA1)"
    if recipe == RECIPE_ARCHIVE_DISC:
        inner = next(m["name"] for m in row.members if _ext(m["name"]) == source)
        row.output = str(parent / f"{PurePosixPath(inner).stem}.{produces}")
        row.note = "unpacked to a work folder first, each file checked against its CRC32"
    else:
        row.output = str(parent / f"{PurePosixPath(row.rel_path).stem}.{produces}")
        if row.parts:
            row.note = f"with its {len(row.parts)} track file(s)"
        elif source == cso.CSO:
            row.note = "decoded to an ISO in a work folder first"
    if delete_originals:
        row.reversible = False
    else:
        row.originals_to = originals_path(settings, label, row.rel_path)


def _cannot_decrypt(settings, profile, card: tuple[bool, str], seeds) -> str | None:
    """Why this encrypted card image cannot be decrypted here, or None."""
    seed, program_id = card
    if settings.card_images.get(profile.card_image or "") is None or not profile.decrypts:
        return "this platform's images are not decrypted here"
    if decrypt.boot9_path(settings) is None:
        return "to decrypt it, add your console's boot9 under Console keys on this page"
    if seed and seeds is None:
        return "it is encrypted with a seed: add your console's seeddb under Console keys"
    if seed and program_id not in seeds:
        return f"its seed (title {program_id or 'unknown'}) is not in the seeddb added"
    return None


def _decrypt(settings, label, row, profile, card, seeds, member, delete_originals) -> None:
    """An encrypted card image, bare or an archive's one ROM (`member`): decrypted when the
    keys it needs are there, else flagged with what is missing. The output proves itself
    against its own hashes (`cards.prove_decrypted`); no DAT is needed."""
    blocked = _cannot_decrypt(settings, profile, card, seeds)
    if blocked:
        row.status, row.note = FLAGGED, blocked
        return
    name = PurePosixPath(member["name"] if member else row.rel_path)
    parent = PurePosixPath(row.rel_path).parent
    row.status, row.recipe, row.card_image = DECRYPT, RECIPE_DECRYPT, profile.card_image
    row.output = str(parent / f"{name.stem}{settings.decryption.output_suffix}{name.suffix}")
    row.source_member = member
    row.verify = "the decrypted image must match the hashes its partitions carry"
    row.note = "decrypted with your console's keys"
    if member:
        row.note = f"{name.name} unpacked to a work folder and decrypted with your console's keys"
    if delete_originals:
        row.reversible = False
    else:
        row.originals_to = originals_path(settings, label, row.rel_path)


def _propose(settings, label, target, row, roms, delete_originals) -> None:
    parent = PurePosixPath(row.rel_path).parent
    disc_formats = {e.lower() for e in settings.platforms.disc_formats}
    if target.produces == PLAIN or (
        target.produces in disc_formats
        and len(roms) == 1
        and _ext(roms[0]["name"]) == target.produces
    ):
        _unwrap(row, roms[0], len(row.members) - len(roms))
    elif target.produces != ZIP:
        row.status, row.note = FLAGGED, f"the app cannot make {target.produces} from this file"
        return
    else:
        row.status, row.recipe = WRAP, RECIPE_WRAP
        row.output = str(parent / f"{PurePosixPath(row.rel_path).stem}.{target.produces}")
        row.verify = f"CRC32 and size of the zipped member equal the file's ({row.size} bytes)"
    _originals(settings, label, row, delete_originals)


def _unwrap(row, member, extras: int) -> None:
    """The archive's one ROM, extracted next to it."""
    row.status, row.recipe = UNWRAP, RECIPE_UNWRAP
    row.output = str(PurePosixPath(row.rel_path).parent / PurePosixPath(member["name"]).name)
    row.verify = f"CRC32 {member['crc32']} and size {member['size']} of the extracted file"
    if extras:
        row.note = f"{extras} other file(s) in the archive stay in the original"


def _originals(settings, label, row, delete_originals) -> None:
    if delete_originals:
        row.reversible = False
    else:
        row.originals_to = originals_path(settings, label, row.rel_path)


def _byteswap(settings, label, target, row, roms, word, byte_order, delete_originals) -> None:
    """A swapped ROM is rewritten in the native order, under the native extension, in the
    target's container. A zip whose new name would be its own becomes a bare ROM first (the
    next conversion wraps it): an output never replaces its source."""
    inner = roms[0] if roms else None
    size = inner["size"] if inner else row.size
    if size is None or size % word:
        row.status = FLAGGED
        row.note = f"byte-swapped, but its size is not a multiple of {word} bytes"
        return
    parent = PurePosixPath(row.rel_path).parent
    stem = PurePosixPath(inner["name"] if inner else row.rel_path).stem
    bare = str(parent / f"{stem}.{byte_order.native_extension}")
    zipped = str(parent / f"{stem}{ZIP_SUFFIX}")
    if target.produces == ZIP and zipped.lower() != row.rel_path.lower():
        row.output, row.output_member = zipped, PurePosixPath(bare).name
    elif bare.lower() != row.rel_path.lower():
        row.output = bare
        if target.produces == ZIP:
            row.note = (
                "taken out of the zip in the native order; zipped again once the original "
                "has left discarded/ (the zip's name is the original's)"
            )
    else:
        row.status = FLAGGED
        row.note = (
            f"named .{byte_order.native_extension} but byte-swapped: rename it (e.g. .v64) "
            "and rescan"
        )
        return
    row.status, row.recipe, row.word_bytes = BYTESWAP, RECIPE_BYTESWAP, word
    row.source_member = inner
    row.verify = "the new file's ROM, swapped back, must equal the original's (SHA1)"
    if delete_originals:
        row.reversible = False
    else:
        row.originals_to = originals_path(settings, label, row.rel_path)


def counts(conversion_rows: list[ConversionRow]) -> dict[str, int]:
    found = Counter(r.status for r in conversion_rows)
    return {s: found.get(s, 0) for s in STATUSES} | {
        "to_convert": sum(found.get(s, 0) for s in CONVERTING),
        "all": len(conversion_rows),
    }
