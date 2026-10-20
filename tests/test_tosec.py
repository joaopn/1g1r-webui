import io
import zipfile
import zlib
from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient

from g1r import tosec
from g1r.dats import parse_dat_bytes
from g1r.grouping import build_groups
from g1r.names import parse_tosec
from g1r.ranking import decide
from g1r.web.app import create_app


def test_tosec_names(make_settings):
    config = make_settings().names.tosec
    p = parse_tosec(
        "Turrican II v1.1 (1991)(Rainbow Arts)(DE)(de-en)(PAL)(Disk 1 of 2)[cr FSS][a2] {D64}",
        config,
    )
    assert (p.title, p.revision, p.regions, p.languages) == (
        "Turrican II",
        "v1.1",
        ("Germany",),
        ("De", "En"),
    )
    # Year, publisher and disk keep games apart; PAL does not; flags rank the dump.
    assert p.other_tags == ("1991", "Rainbow Arts", "Disk 1 of 2")
    assert p.dump_flags == ("cr", "a")
    clean = parse_tosec("Turrican II (1991)(Rainbow Arts)", config)
    verified = parse_tosec("Turrican II (1991)(Rainbow Arts)[!]", config)
    cracked = parse_tosec("Turrican II (1991)(Rainbow Arts)[cr X]", config)
    assert verified.dump < clean.dump < cracked.dump < p.dump
    assert parse_tosec("Game (demo) (1990)(Pub)", config).prerelease


def dat(header: str, games: dict[str, bytes], ext: str) -> bytes:
    body = "".join(
        f'<game name="{n}"><description>{n}</description><rom name="{n}.{ext}" '
        f'size="{len(d)}" crc="{zlib.crc32(d):08x}"/></game>'
        for n, d in games.items()
    )
    return (
        f"<?xml version='1.0'?><datafile><header><name>{header}</name>"
        f"<version>2025-01-01</version></header>{body}</datafile>"
    ).encode()


GAME = "Wizball (1987)(Ocean)"
PACK_DATS = {
    "TOSEC/Commodore C64 - Games - Arcade - [D64] (TOSEC-v2025_CM).dat": dat(
        "Commodore C64 - Games - Arcade - [D64]",
        {GAME: b"d64", f"{GAME}[cr X]": b"crack", f"{GAME}[cr X][a]": b"crack2"},
        "d64",
    ),
    "TOSEC/Commodore C64 - Games - Arcade - [TAP] (TOSEC-v2025_CM).dat": dat(
        "Commodore C64 - Games - Arcade - [TAP]", {GAME: b"tap"}, "tap"
    ),
    "TOSEC/Commodore C64 - Demos - [D64] (TOSEC-v2025_CM).dat": dat(
        "Commodore C64 - Demos - [D64]", {"A Demo (1990)(Group)": b"demo"}, "d64"
    ),
    "TOSEC/Commodore Amiga - Games - [ADF] (TOSEC-v2025_CM).dat": dat(
        "Commodore Amiga - Games - [ADF]", {"Turrican (1990)(Rainbow Arts)": b"adf"}, "adf"
    ),
    # Disc systems are in TOSEC-ISO/; Dreamcast leaves its firmware DAT out.
    "TOSEC-ISO/Sega Dreamcast - Games - [CDI] (TOSEC-v2025_CM).dat": dat(
        "Sega Dreamcast - Games - [CDI]", {"Karous (2007)(Milestone)(JP)[cr]": b"cdi"}, "cdi"
    ),
    "TOSEC-ISO/Sega Dreamcast - Firmware (TOSEC-v2017_CM).dat": dat(
        "Sega Dreamcast - Firmware", {"Dreamcast BIOS (1998)(Sega)": b"bios"}, "bin"
    ),
}


def pack() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for name, data in PACK_DATS.items():
            z.writestr(name, data)
        z.writestr("readme.txt", "TOSEC")
    return buffer.getvalue()


def test_a_platform_takes_its_dats_merged_and_names_stay_unique(make_settings):
    settings = make_settings()
    profile = settings.platforms.profiles["c64"]
    archive = zipfile.ZipFile(io.BytesIO(pack()))
    dats = tosec.platform_dats(archive, "TOSEC/", profile.tosec_prefixes, 10**6)
    merged = parse_dat_bytes(tosec.merge(dats, profile.dat_name))
    assert merged.header.name == profile.dat_name
    names = sorted(g.name for g in merged.games)
    # The demo DAT is not a game DAT; the release in both formats gets its format.
    assert names == [f"{GAME} {{D64}}", f"{GAME} {{TAP}}", f"{GAME}[cr X]", f"{GAME}[cr X][a]"]
    ranking = settings.ranking.model_copy(update={"criteria": profile.ranking_criteria})
    (group,) = build_groups(
        settings, merged, [(f"{n}.x", n, "dat-checksum") for n in names], "name", "tosec"
    )
    # Clean dumps first: the D64 and the TAP of the original tie, so it stays undecided.
    decision = decide(group, ranking)
    assert decision.winner is None
    assert sorted(v.game_name for v in decision.candidates) == names[:2]


@pytest.fixture
def client(make_settings):
    pages = {
        "https://www.tosecdev.org/downloads": (
            b'<a href="/downloads/category/58-2024-05-17">old</a>'
            b'<a href="/downloads/category/59-2025-03-13">new</a>'
        ),
        "https://www.tosecdev.org/downloads/category/59-2025-03-13": (
            b'<a href="/downloads/category/59-2025-03-13?download=117:'
            b'tosec-dat-pack-complete-4743-tosec-v2025-03-13">pack</a>'
        ),
    }
    fetched = []

    def fetch(url):
        fetched.append(url)
        return pages.get(url) or pack()

    with TestClient(create_app(make_settings(), fetch=fetch)) as c:
        yield c, fetched


def test_download_finds_the_newest_pack_once_and_merges_per_platform(client):
    c, fetched = client
    response = c.post("/api/dats/c64/download?source=tosec")
    assert response.status_code == HTTPStatus.OK, response.json()
    assert fetched[-1] == (
        "https://www.tosecdev.org/downloads/category/59-2025-03-13"
        "?download=117:tosec-dat-pack-complete-4743-tosec-v2025-03-13"
    )
    pack_requests = len(fetched)
    assert c.post("/api/dats/amiga/download?source=tosec").status_code == HTTPStatus.OK
    # The pack was kept: only the two pages were asked again.
    assert len(fetched) == pack_requests + 2


def test_uploading_the_pack_fills_every_tosec_platform(client):
    c, _ = client
    results = c.post("/api/dats/pack", files={"file": ("tosec.zip", pack())}).json()
    assert {(r["platform"], r["message"]) for r in results} == {
        ("amiga", "added"),
        ("c64", "added"),
        ("dc", "added"),
    }


def test_dreamcast_takes_its_dats_from_tosec_iso(make_settings):
    profile = make_settings().platforms.profiles["dc"]
    archive = zipfile.ZipFile(io.BytesIO(pack()))
    dats = tosec.platform_dats(archive, profile.tosec_dir, profile.tosec_prefixes, 10**6)
    merged = parse_dat_bytes(tosec.merge(dats, profile.dat_name))
    assert [g.name for g in merged.games] == ["Karous (2007)(Milestone)(JP)[cr]"]
