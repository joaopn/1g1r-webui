import zipfile
import zlib
from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient

from g1r import igir
from g1r.web.app import create_app

PARENT, CLONE, OTHER_CLONE, BIOS = "pg", "pgh", "pgb", "neogeo"


def rom(name: str, data: bytes, merge: str | None = None) -> str:
    extra = f' merge="{merge}"' if merge else ""
    return f'<rom name="{name}" size="{len(data)}" crc="{zlib.crc32(data):08x}"{extra}/>'


DAT = (
    "<?xml version='1.0'?><datafile><header><name>FinalBurn Neo - Neo Geo Games</name>"
    "<description>FinalBurn Neo v1 Neo Geo Games</description></header>"
    f'<game isbios="yes" name="{BIOS}"><description>Neo Geo</description>'
    f"{rom('sp.sp1', b'bios')}</game>"
    f'<game name="{PARENT}" romof="{BIOS}"><description>Parent Game</description>'
    f"{rom('p.p1', b'parent')}</game>"
    f'<game name="{CLONE}" cloneof="{PARENT}" romof="{PARENT}">'
    f"<description>Parent Game (hack)</description>{rom('h.p1', b'hack')}</game>"
    f'<game name="{OTHER_CLONE}" cloneof="{PARENT}" romof="{PARENT}">'
    f"<description>Parent Game (bootleg)</description>{rom('b.p1', b'boot')}</game>"
    "</datafile>"
).encode()


@pytest.fixture
def mvs(make_settings, roms_root):
    folder = roms_root / "mvs"
    folder.mkdir()
    (roms_root / "discarded").mkdir()
    for name in (PARENT, CLONE, BIOS):
        with zipfile.ZipFile(folder / f"{name}.zip", "w") as z:
            z.writestr("chip.bin", name.encode())
            z.writestr("chip2.bin", name.encode() * 2)
    (folder / "loose.bin").write_bytes(b"chip")
    modes = []

    def report(settings, dat_file, root, merge=None, **_):
        modes.append(merge)
        # The split run finds the parent and the BIOS; the non-merged run the clone.
        found = {"split": [PARENT, BIOS], "nonmerged": [CLONE]}[merge]
        return [igir.ReportRow(g, "FOUND", (str(root / f"{g}.zip"),)) for g in found]

    fetched = []

    def fetch(url):
        fetched.append(url)
        return DAT

    app = create_app(make_settings(), fetch=fetch, report_runner=report)
    with TestClient(app) as client:
        body = {"platform": "neogeomvs", "mount": "roms", "path": "mvs", "label": "mvs"}
        assert client.post("/api/folders", json=body).status_code == HTTPStatus.CREATED
        yield client, modes, fetched


def scan(client):
    client.post("/api/folders/mvs/scan")
    for _ in range(500):
        if client.get("/api/folders/mvs/scan").json()["status"] != "running":
            return
    raise AssertionError("scan did not finish")


def test_fbneo_dat_download_and_sets_identified_in_both_merge_modes(mvs):
    client, modes, fetched = mvs
    assert (
        client.post("/api/dats/neogeomvs/download?source=fbneo").status_code
        < HTTPStatus.BAD_REQUEST
    )
    assert fetched == [
        "https://raw.githubusercontent.com/libretro/FBNeo/master/dats/"
        "FinalBurn%20Neo%20%28ClrMame%20Pro%20XML%2C%20Neogeo%20only%29.dat"
    ]
    scan(client)
    assert modes == ["split", "nonmerged"]
    games = {g["name"]: g for g in client.get("/api/folders/mvs/games").json()}
    # Titles come from the descriptions; the parent is kept, its clone proposed.
    game = games["Parent Game"]
    assert game["status"] == "decided" and game["kept"] == f"{PARENT}.zip"
    titles = {v["rel_path"]: (v["title"], v["operation"] is not None) for v in game["versions"]}
    assert titles == {
        f"{PARENT}.zip": ("Parent Game", False),
        f"{CLONE}.zip": ("Parent Game (hack)", True),
    }
    bios = games["Neo Geo"]
    assert bios["status"] == "left alone" and "BIOS" in bios["reason"]
    rows = {r["rel_path"]: r for r in client.get("/api/folders/mvs/conversion").json()["rows"]}
    # Romsets are whole games, never "several ROM files to split".
    assert {rows[f"{n}.zip"]["status"] for n in (PARENT, CLONE, BIOS)} == {"done"}
    assert rows["loose.bin"]["status"] == "flagged"
