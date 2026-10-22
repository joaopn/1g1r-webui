from contextlib import closing
from pathlib import Path

from g1r import db, discarded, statistics
from g1r.dats import Dat, DatGame, DatHeader, DatRom
from g1r.grouping import NOINTRO_STYLE, TOSEC_STYLE

from .test_api import scanned, setup  # noqa: F401  (the fixture)

DATA = Path(__file__).parent / "data"


def game(name, crc, category=None, rom_name=None, **extra):
    rom = DatRom(rom_name or f"{name}.nes", 16, crc, None, None)
    return DatGame(name, category=category, roms=[rom], **extra)


def dat(*games):
    return Dat(DatHeader("Nintendo - Nintendo Entertainment System"), list(games), "logiqx")


def connect(settings):
    return db.connect(settings.paths.database_path, settings.database.busy_timeout_ms)


def settings_of(make_settings):
    return make_settings({"grouping": {"retool_clonelists_dir": str(DATA / "none")}})


def test_only_games_count(make_settings):
    s = settings_of(make_settings)
    assert statistics.is_game(s, [game("Contra (USA)", "01")], NOINTRO_STYLE)
    # Unlicensed releases are games.
    assert statistics.is_game(s, [game("Tetris (USA) (Unl)", "02")], NOINTRO_STYLE)
    for name in ["Contra (USA) (Beta 2)", "Contra (USA) (Proto, Unl)", "Contra (Pirate)"]:
        assert not statistics.is_game(s, [game(name, "03")], NOINTRO_STYLE), name
    assert not statistics.is_game(s, [game("Contra (USA)", "04", "Demos")], NOINTRO_STYLE)
    assert statistics.is_game(s, [game("Contra (USA)", "05", "Games")], NOINTRO_STYLE)
    # The libretro mirror tags some entries on the ROM name only.
    tagged = game("!Clik! (World)", "06", rom_name="!Clik! (World) (Aftermarket) (Unl).nes")
    assert not statistics.is_game(s, [tagged], NOINTRO_STYLE)
    assert not statistics.is_game(s, [game("[BIOS] Famicom (Japan)", "07")], NOINTRO_STYLE)
    assert not statistics.is_game(s, [game("Sys", "08", bios=True)], NOINTRO_STYLE)
    # TOSEC: modified dumps and pre-releases are left out, not a publisher with a tag word.
    tosec = [
        ("Elite (1985)(Firebird)", True),
        ("Elite (1985)(Program Systems)", True),
        ("Elite (1985)(Firebird)[h Fairlight]", False),
        ("Elite (1985)(Firebird)[cr]", False),
        ("Elite (1985)(Firebird)(beta)", False),
    ]
    for name, kept in tosec:
        assert statistics.is_game(s, [game(name, "09")], TOSEC_STYLE) is kept, name


def test_coverage_counts_games_one_version_is_enough(make_settings):
    s = settings_of(make_settings)
    local = dat(
        game("Contra (USA)", "01"),
        game("Contra (Japan)", "02"),
        game("Gradius (USA)", "03"),
        game("Gradius (USA) (Proto)", "04"),
        game("Unreleased (USA) (Proto)", "05"),
        game("Solo (Japan)", "06", year="1987", manufacturer="Konami"),
        game("Solo (USA)", "07", year="1988", manufacturer="Konami"),
        game("Tetris (USA) (Tengen)", "08", rom_name="Tetris (USA) (Tengen) (Unl).nes"),
    )
    games = statistics.dat_games(s, "local", local, NOINTRO_STYLE, "name")
    # Contra, Gradius and Solo; the prototype-only game is not counted.
    assert sorted(games.labels.values()) == ["Contra", "Gradius", "Solo", "Tetris (Tengen)"]

    # The Japanese Contra; only the prototype of Gradius (it covers nothing).
    have = statistics.Identified({"Contra (Japan)", "Gradius (USA) (Proto)"})
    covered, total, missing = statistics.coverage(games, have)
    assert (covered, total) == (1, 4)
    rows = statistics.missing_rows(s, games, missing)
    assert [r["name"] for r in rows] == ["Gradius", "Solo", "Tetris (Tengen)"]
    # Obs: the other tags, the spelled-out ones first, from the ROM names too.
    assert rows[2]["notes"] == "Unlicensed, Tengen" and rows[2]["marked"]
    assert rows[1]["notes"] is None and not rows[1]["marked"]
    solo = rows[1]
    assert solo["years"] == "1987, 1988" and solo["publishers"] == "Konami"
    assert solo["regions"] == "Japan, USA" and solo["versions"] == 2


def test_a_file_from_another_dat_covers_by_checksums(make_settings):
    s = settings_of(make_settings)
    games = statistics.dat_games(
        s, "other", dat(game("Contra (USA) (Other Name)", "0a")), NOINTRO_STYLE, "name"
    )
    have = statistics.Identified({"Contra (USA)"}, {("crc", "0a", 16)})
    assert statistics.coverage(games, have)[:2] == (1, 1)
    assert statistics.coverage(games, statistics.Identified({"Contra (USA)"}))[:2] == (0, 1)


def test_statistics_api(setup):  # noqa: F811
    client, _, _ = setup
    scanned(client)
    body = client.get("/api/statistics").json()
    folder = body["folders"][0]
    assert folder["label"] == "nes" and folder["identified"] == 5
    cells = list(folder["coverage"].values())
    assert cells and all(c["covered"] == c["total"] for c in cells)
    source = next(iter(folder["coverage"]))
    assert {s["id"] for s in body["sources"]} >= {source}
    info = next(i for i in body["dat_info"] if i["id"] == source)
    assert info["dats"] == 1 and info["checksums"] == ["CRC32"]
    missing = client.get(f"/api/statistics/nes/{source}/missing").json()
    assert missing["rows"] == []
    assert client.get("/api/statistics/nes/nope/missing").status_code == 404


def test_statistics_show_the_set_and_discarded_sizes_live(setup):  # noqa: F811
    client, _, settings = setup
    scanned(client)
    folder = client.get("/api/statistics").json()["folders"][0]
    summary = client.get("/api/folders/nes").json()["summary"]
    assert folder["bytes"] == summary["bytes"] > 0
    assert folder["discarded_bytes"] == 0
    trash = discarded.folder_root(settings, "nes") / "manual"
    trash.mkdir(parents=True)
    (trash / "old.zip").write_bytes(b"x" * 10)
    # Not part of the kept figures: a new file in discarded/ shows without a refresh.
    assert client.get("/api/statistics").json()["folders"][0]["discarded_bytes"] == 10


def test_statistics_are_kept_until_refreshed(setup):  # noqa: F811
    client, _, settings = setup
    scanned(client)
    first = client.get("/api/statistics").json()["folders"][0]
    assert first["stale"] is False and first["computed_at"]
    with closing(connect(settings)) as conn:
        conn.execute("UPDATE statistics_cache SET value = json_set(value, '$.roms', -1)")
        kept = client.get("/api/statistics").json()["folders"][0]
        assert kept["roms"] == -1 and kept["stale"] is False
        # A file losing its identity marks the figures as changed, without recomputing them.
        conn.execute("DELETE FROM identity WHERE rowid = (SELECT min(rowid) FROM identity)")
    changed = client.get("/api/statistics").json()["folders"][0]
    assert changed["roms"] == -1 and changed["stale"] is True
    fresh = client.post("/api/statistics/refresh").json()["folders"][0]
    assert fresh["stale"] is False and fresh["identified"] == first["identified"] - 1
    assert fresh["roms"] == first["roms"]


def test_missing_games_follow_the_folder(setup):  # noqa: F811
    client, _, settings = setup
    scanned(client)
    source = next(iter(client.get("/api/statistics").json()["folders"][0]["coverage"]))
    url = f"/api/statistics/nes/{source}/missing"
    before = client.get(url).json()
    assert before["rows"] == []
    with closing(connect(settings)) as conn:
        conn.execute("DELETE FROM identity")
    after = client.get(url).json()
    assert after["covered"] == 0 and len(after["rows"]) == after["total"]
