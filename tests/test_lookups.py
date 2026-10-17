import json
import zlib
from http import HTTPStatus

from g1r import fuzzy, hasheous, hashing, scanner, unmatched
from g1r.config import FuzzyConfig

from .test_scanner import BODY, NES_HEADER, env  # noqa: F401  (fixture)

DAT = "Nintendo - Nintendo Entertainment System"


def signature(system: str, description: str) -> dict:
    return {"game": {"system": system, "description": description}, "rom": {"name": "x.nes"}}


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
    unlisted = answer(signature("Nintendo - Game Boy", "Tetris (World)"), source="TOSEC")
    assert hasheous.read_answer(settings, unlisted, "Nintendo - Game Boy").status == (
        hasheous.NOT_FOUND
    )


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


LOOSE = "sub/Loose (Europe).nes"


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
