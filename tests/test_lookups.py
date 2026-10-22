import hashlib
import json
import zipfile
import zlib
from http import HTTPStatus
from pathlib import Path

from g1r import fuzzy, hasheous, hashing, scanner, unmatched
from g1r.config import FuzzyConfig

from .test_scanner import BODY, NES_HEADER, env  # noqa: F401  (fixture)

DAT = "Nintendo - Nintendo Entertainment System"


DATA = Path(__file__).parent / "data"


def signature(system: str, description: str, rom: str | None = None) -> dict:
    rom_name = rom or f"{description}.nes"
    return {"game": {"system": system, "description": description}, "rom": {"name": rom_name}}


def answer(*entries, source="NoIntros") -> dict:
    return {"signatures": {source: list(entries)}}


class FakeHasheous:
    """Answers by SHA1; records what was asked."""

    def __init__(self, answers: dict[str, dict] | None = None, status: int | None = None):
        self.answers = answers or {}
        self.status = status
        self.asked: list[dict] = []

    def __call__(self, url, body, headers, timeout):
        sent = json.loads(body)
        self.asked.append(sent)
        if self.status is not None:
            return self.status, b""
        found = self.answers.get(sent["sha1"])
        if found is None:
            return HTTPStatus.NOT_FOUND, b"not found"
        return HTTPStatus.OK, json.dumps(found).encode()


def test_content_hashes_include_the_headerless_data(env):  # noqa: F811
    settings, *_ = env
    path = settings.paths.roms_root / "nes" / "Known (USA).zip"
    hashes = {h.variant: h for h in hashing.content_hashes(settings, "nes", path)}
    assert set(hashes) == {hashing.FULL, hashing.HEADERLESS}
    assert hashes[hashing.HEADERLESS].crc32 == format(zlib.crc32(BODY), "08x")
    assert hashes[hashing.FULL].size == len(NES_HEADER + BODY)


def test_answers_count_only_for_the_folders_platform(make_settings):
    settings = make_settings()
    gba = answer(signature("Nintendo - Game Boy Advance", "Pokemon (USA)"))
    assert hasheous.read_answer(settings, gba, "Nintendo - Game Boy").status == (
        hasheous.OTHER_PLATFORM
    )
    gb = answer(signature("Nintendo - Game Boy (Parent-Clone)", "Tetris (World)"))
    found = hasheous.read_answer(settings, gb, "Nintendo - Game Boy")
    assert (found.status, found.game_name, found.detail) == (
        hasheous.FOUND,
        "Tetris (World)",
        "No-Intro",
    )
    unlisted = answer(signature("Nintendo - Game Boy", "Tetris (World)"), source="PureDOSDAT")
    assert hasheous.read_answer(settings, unlisted, "Nintendo - Game Boy").status == (
        hasheous.NOT_FOUND
    )


def test_other_sources_identify_only_with_a_name_the_platforms_dats_list(make_settings):
    """A real answer (Tetris (World) (Rev 1), Game Boy): No-Intro, TOSEC and
    RetroAchievements entries, each source writing the system its own way."""
    settings = make_settings()
    real = json.loads((DATA / "hasheous-tetris.json").read_text())
    gb = settings.platforms.profiles["gb"]
    without_no_intro = {
        "signatures": {k: v for k, v in real["signatures"].items() if k != "NoIntros"}
    }
    # RetroAchievements names the ROM as No-Intro does, and the DAT lists that name.
    listed = hasheous.platform(gb, {"Tetris (World) (Rev 1)"})
    found = hasheous.read_answer(settings, without_no_intro, listed)
    assert (found.status, found.game_name, found.detail) == (
        hasheous.FOUND,
        "Tetris (World) (Rev 1)",
        "RetroAchievements",
    )
    # No DAT lists those names: TOSEC's and RetroAchievements' names are only hints.
    hint = hasheous.read_answer(settings, without_no_intro, hasheous.platform(gb))
    assert hint.status == hasheous.NOT_IN_DAT and hint.game_name is None
    assert hint.known_as == (
        "Tetris Rev 1 (1989)(Nintendo)(EU-US)",
        "Tetris (World) (Rev 1)",
    )
    assert hint.detail == "TOSEC: Tetris Rev 1 (1989)(Nintendo)(EU-US)"
    # "Nintendo Game Boy" and "Game Boy" are Game Boy; none of them is Game Boy Color.
    gbc = hasheous.platform(settings.platforms.profiles["gbc"], {"Tetris (World) (Rev 1)"})
    assert hasheous.read_answer(settings, without_no_intro, gbc).status == (hasheous.OTHER_PLATFORM)


def test_the_name_comes_from_the_rom_for_no_intro_and_the_game_for_redump(make_settings):
    settings = make_settings()
    stale = signature(DAT, "Doraemon (Japan)", rom="Doraemon (Japan) (Rev 1).nes")
    found = hasheous.read_answer(settings, answer(stale), DAT)
    assert found.game_name == "Doraemon (Japan) (Rev 1)"
    stripped = [
        signature("Nintendo - Game Boy", "Aa Harimanada (Japan)", rom="Aa Harimanada.gb"),
        signature("Nintendo - Game Boy (Parent-Clone)", "Aa Harimanada (Japan)"),
    ]
    for entries in (stripped, stripped[:1]):
        found = hasheous.read_answer(settings, answer(*entries), "Nintendo - Game Boy")
        assert found.game_name == "Aa Harimanada (Japan)"
    disc = signature("Sony - PlayStation", "Game (USA)", rom="Game (USA) (Track 1).bin")
    found = hasheous.read_answer(settings, answer(disc, source="Redump"), "Sony - PlayStation")
    assert found.game_name == "Game (USA)"


def test_answers_are_cached_and_not_found_is_asked_again_on_refresh(env):  # noqa: F811
    settings, _, _, conn, _ = env
    h = hashing.ContentHash("full", 1, "00000000", "0" * 32, "a" * 40)
    post = FakeHasheous()
    for _ in range(2):
        assert hasheous.lookup(settings, conn, [h], DAT, post).status == hasheous.NOT_FOUND
    assert len(post.asked) == 1
    hasheous.lookup(settings, conn, [h], DAT, post, refresh=True)
    assert len(post.asked) == 2
    assert post.asked[0] == {"crc": "00000000", "md5": "0" * 32, "sha1": "a" * 40}


def test_suggestions_list_a_name_the_dat_repeats_once():
    config = FuzzyConfig(min_score=0.5, max_suggestions=3, auto_match_threshold=None)
    best = fuzzy.suggestions(config, "Tetris (USA).zip", ["Tetris (USA)", "Tetris (USA)"])
    assert [name for name, _ in best] == ["Tetris (USA)"]


def test_suggestions_best_first_above_the_minimum():
    config = FuzzyConfig(min_score=0.6, max_suggestions=2, auto_match_threshold=None)
    names = ["Doraemon (Japan)", "Doraemon (Japan) (Rev 1)", "Dragon Power (USA)", "Zelda"]
    best = fuzzy.suggestions(config, "nes/Doraemon (Japan) (Rev 1) [b].zip", names)
    assert [name for name, _ in best] == ["Doraemon (Japan) (Rev 1)", "Doraemon (Japan)"]
    assert all(0.6 <= score <= 1 for _, score in best)


def scan(env, post=None, **settings_changes):  # noqa: F811
    settings, store, registry, conn, folder_scanner = env
    if settings_changes:
        store.update(lambda lib: [setattr(lib.lookups, k, v) for k, v in settings_changes.items()])
    if post is not None:
        folder_scanner.lookup_post = post
    folder_scanner.run(conn, folder_scanner.start(conn, "nes"), "nes")
    return conn, scanner.latest_scan(conn, "nes")


LOOSE = "sub/Loose (Europe).zip"


def loose_sha1(conn) -> str:
    return conn.execute(
        "SELECT sha1 FROM content_hash WHERE rel_path = ? AND variant = 'full'", (LOOSE,)
    ).fetchone()[0]


def test_lookups_are_off_by_default_and_nothing_is_sent(env):  # noqa: F811
    post = FakeHasheous()
    conn, result = scan(env, post)
    assert result["status"] == "done" and post.asked == []
    assert loose_sha1(conn)  # hashed all the same, ready for a lookup
    (row,) = unmatched.rows(conn, "nes", hasheous_on=False)
    assert row["rel_path"] == LOOSE and row["hasheous"]["status"] == "off"


def test_hasheous_identifies_what_the_dat_missed(env):  # noqa: F811
    conn, _ = scan(env)
    post = FakeHasheous(
        {loose_sha1(conn): answer(signature(f"{DAT} (Headered)", "Loose (Europe)"))}
    )
    conn, result = scan(env, post, hasheous=True)
    assert "1 of them via Hasheous" in result["message"]
    method = conn.execute("SELECT method FROM identity WHERE rel_path = ?", (LOOSE,)).fetchone()
    assert method[0] == scanner.METHOD_HASHEOUS
    assert unmatched.rows(conn, "nes", hasheous_on=True) == []


def test_an_archive_with_several_roms_is_not_looked_up(env):  # noqa: F811
    settings, *_ = env
    with zipfile.ZipFile(settings.paths.roms_root / "nes" / "Pack.zip", "w") as pack:
        pack.writestr("One (USA).nes", b"one")
        pack.writestr("Two (USA).nes", b"two")
    post = FakeHasheous()
    conn, _ = scan(env, post, hasheous=True)
    rows = {r["rel_path"]: r for r in unmatched.rows(conn, "nes", hasheous_on=True)}
    assert rows["Pack.zip"]["hasheous"] == {
        "status": hasheous.SKIPPED,
        "detail": "several ROM files in one archive",
    }
    assert len(post.asked) == 1  # only the loose file


def test_a_file_larger_than_a_read_is_hashed_whole_and_looked_up(env, make_settings):  # noqa: F811
    _, store, registry, conn, _ = env
    small_reads = make_settings({"hashing": {"chunk_bytes": 5}})
    post = FakeHasheous()
    folder_scanner = scanner.Scanner(
        small_reads, store, registry, lambda *a, **_: [], lookup_post=post
    )
    store.update(lambda lib: setattr(lib.lookups, "hasheous", True))
    folder_scanner.run(conn, folder_scanner.start(conn, "nes"), "nes")
    assert hashlib.sha1(b"unknown data").hexdigest() in [sent["sha1"] for sent in post.asked]


def test_hashes_read_in_pieces_equal_the_whole_files(env, make_settings):  # noqa: F811
    settings, *_ = env
    path = settings.paths.roms_root / "nes" / "Known (USA).zip"
    for chunk in (3, 16, 17, 4096):
        small_reads = make_settings({"hashing": {"chunk_bytes": chunk}})
        hashes = {h.variant: h for h in hashing.content_hashes(small_reads, "nes", path)}
        assert hashes[hashing.FULL].sha1 == hashlib.sha1(NES_HEADER + BODY).hexdigest()
        assert hashes[hashing.HEADERLESS].md5 == hashlib.md5(BODY).hexdigest()
        assert hashes[hashing.HEADERLESS].size == len(BODY)


def test_a_lookup_error_leaves_the_file_unmatched_and_says_so(env):  # noqa: F811
    conn, result = scan(env, FakeHasheous(status=HTTPStatus.BAD_GATEWAY), hasheous=True)
    assert result["status"] == "done" and "online lookups stopped" in result["message"]
    (row,) = unmatched.rows(conn, "nes", hasheous_on=True)
    assert row["hasheous"]["status"] == hasheous.ERROR


def test_manual_assignment_survives_rescans_and_can_be_undone(env):  # noqa: F811
    conn, _ = scan(env)
    unmatched.assign(conn, "nes", LOOSE, "Known (USA)")
    assert unmatched.rows(conn, "nes", hasheous_on=False) == []
    conn, _ = scan(env)
    row = conn.execute("SELECT method FROM identity WHERE rel_path = ?", (LOOSE,)).fetchone()
    assert row[0] == scanner.METHOD_MANUAL
    unmatched.assign(conn, "nes", LOOSE, None)
    assert [r["rel_path"] for r in unmatched.rows(conn, "nes", hasheous_on=False)] == [LOOSE]


def test_fuzzy_auto_match_only_with_a_threshold(env, make_settings):  # noqa: F811
    settings, store, registry, conn, folder_scanner = env
    # "Loose (Europe)" is close to nothing in the DAT: with a low bar it auto-matches.
    folder_scanner.settings = settings.model_copy(
        update={"fuzzy": FuzzyConfig(min_score=0.1, max_suggestions=3, auto_match_threshold=0.1)}
    )
    conn, _ = scan(env)
    row = conn.execute("SELECT method, score FROM identity WHERE rel_path = ?", (LOOSE,)).fetchone()
    assert row["method"] == scanner.METHOD_FUZZY and 0.1 <= row["score"] < 1


def test_another_sources_name_identifies_only_when_the_dat_lists_it(env):  # noqa: F811
    conn, _ = scan(env)
    sha1 = loose_sha1(conn)
    listed = {"game": {"system": "NES/Famicom"}, "rom": {"name": "Reheadered (Japan).nes"}}
    conn, _ = scan(
        env, FakeHasheous({sha1: answer(listed, source="RetroAchievements")}), hasheous=True
    )
    row = conn.execute("SELECT game_name, method FROM identity WHERE rel_path = ?", (LOOSE,))
    assert tuple(row.fetchone()) == ("Reheadered (Japan)", scanner.METHOD_HASHEOUS)


def test_another_sources_unlisted_name_becomes_a_suggestion(env):  # noqa: F811
    conn, _ = scan(env)
    sha1 = loose_sha1(conn)
    tosec = {
        "game": {"system": "Nintendo Entertainment System"},
        "rom": {"name": "Known (1987)(Nintendo)(US).nes"},
    }
    conn, _ = scan(env, FakeHasheous({sha1: answer(tosec, source="TOSEC")}), hasheous=True)
    (row,) = unmatched.rows(conn, "nes", hasheous_on=True)
    assert row["hasheous"] == {
        "status": hasheous.NOT_IN_DAT,
        "detail": "TOSEC: Known (1987)(Nintendo)(US)",
    }
    assert row["suggestions"][0]["game_name"] == "Known (USA)"


def test_unmatched_files_are_hashed_only_for_lookups(env, make_settings):  # noqa: F811
    """With online lookups off, nothing needs an unmatched file's hashes: it is not read.
    (Header rules off here: the header-stripped check reads unmatched files on its own.)"""
    _, store, registry, conn, _ = env
    no_headers = make_settings({"headers": {"nes": []}})
    folder_scanner = scanner.Scanner(no_headers, store, registry, lambda *a, **_: [])
    count = "SELECT COUNT(*) FROM content_hash WHERE rel_path = ?"
    folder_scanner.run(conn, folder_scanner.start(conn, "nes"), "nes")
    assert conn.execute(count, (LOOSE,)).fetchone()[0] == 0
    store.update(lambda lib: setattr(lib.lookups, "hasheous", True))
    folder_scanner = scanner.Scanner(
        no_headers, store, registry, lambda *a, **_: [], lookup_post=FakeHasheous()
    )
    folder_scanner.run(conn, folder_scanner.start(conn, "nes"), "nes")
    assert conn.execute(count, (LOOSE,)).fetchone()[0] > 0
