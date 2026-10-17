import json
from http import HTTPStatus

import pytest

from g1r import scanner, screenscraper, unmatched
from g1r.config import ScreenScraperConfig, ScreenScraperEnvironment
from g1r.hashing import ContentHash

from .test_lookups import LOOSE, loose_sha1, scan
from .test_scanner import env  # noqa: F401  (fixture)

CREDENTIALS = {
    "SCREENSCRAPER_DEVID": "dev",
    "SCREENSCRAPER_DEVPASSWORD": "devpass",
    "SCREENSCRAPER_USER": "me",
    "SCREENSCRAPER_PASSWORD": "mine",
}
HASH = ContentHash("full", 12, "0badc0de", "m" * 32, "s" * 40)


def game(*roms, names=("Le Jeu",), quota=("10", "20000")) -> dict:
    return {
        "response": {
            "ssuser": {"requeststoday": quota[0], "maxrequestsperday": quota[1]},
            "jeu": {
                "noms": [{"region": "wor", "text": n} for n in names],
                "rom": roms[0] if roms else {},
                "roms": list(roms[1:]),
            },
        }
    }


def rom(filename: str, sha1: str = HASH.sha1) -> dict:
    return {"romfilename": filename, "romsha1": sha1}


# Reading answers ---------------------------------------------------------------------


def test_an_answer_identifies_only_with_our_data_and_a_dat_name():
    found = screenscraper.read_answer(game(rom("Known (USA).nes")), HASH, {"Known (USA)"})
    assert (found.status, found.game_name) == (screenscraper.FOUND, "Known (USA)")

    renamed = screenscraper.read_answer(game(rom("Known (U) [!].nes")), HASH, {"Known (USA)"})
    assert (renamed.status, renamed.known_as) == (screenscraper.NOT_IN_DAT, "Known (U) [!]")

    other = screenscraper.read_answer(
        game(rom("Known (USA).nes", sha1="f" * 40)), HASH, {"Known (USA)"}
    )
    assert other.status == screenscraper.NOT_IN_DAT and other.game_name is None
    assert other.known_as == "Le Jeu" and "different ROM" in other.detail


def test_a_crc_counts_only_with_the_size():
    by_crc = {"romfilename": "Known (USA).nes", "romcrc": "0BADC0DE", "romsize": "12"}
    assert screenscraper.read_answer(game(by_crc), HASH, {"Known (USA)"}).status == "found"
    wrong_size = by_crc | {"romsize": "13"}
    assert screenscraper.read_answer(game(wrong_size), HASH, {"Known (USA)"}).status != "found"


# The session ---------------------------------------------------------------------------


def config(**changes) -> ScreenScraperConfig:
    values = {
        "url": "https://ss.example/jeuInfos.php",
        "site": "https://ss.example",
        "softname": "test",
        "user_agent": "test",
        "timeout_seconds": 1,
        "min_interval_seconds": 2,
        "quota_reserve": 5,
        "quota_statuses": [430, 431],
        "not_found_ttl_days": 30,
        "environment": ScreenScraperEnvironment(
            devid="SCREENSCRAPER_DEVID",
            devpassword="SCREENSCRAPER_DEVPASSWORD",
            user="SCREENSCRAPER_USER",
            password="SCREENSCRAPER_PASSWORD",
        ),
    }
    return ScreenScraperConfig(**(values | changes))


def test_credentials_come_from_the_environment():
    assert screenscraper.credentials(config(), {}) is None
    creds = screenscraper.credentials(config(), CREDENTIALS)
    assert (creds.devid, creds.ssid) == ("dev", "me")


def test_requests_are_spaced_and_stop_at_the_quota():
    now = [0.0]
    slept = []
    urls = []

    def get(url, headers, timeout):
        urls.append(url)
        return HTTPStatus.OK, json.dumps(game(rom("x.nes"), quota=("19996", "20000"))).encode()

    session = screenscraper.Session(
        config(),
        screenscraper.credentials(config(), CREDENTIALS),
        get,
        clock=lambda: now[0],
        sleep=lambda s: (slept.append(s), now.__setitem__(0, now[0] + s)),
    )
    status, body = session.request({"sha1": "a"})
    session.note_quota(json.loads(body))
    assert "devid=dev" in urls[0] and "ssid=me" in urls[0] and "sha1=a" in urls[0]
    with pytest.raises(screenscraper.LookupError_, match="quota"):
        session.request({"sha1": "b"})
    assert len(urls) == 1 and slept == []


def test_a_quota_status_stops_the_session():
    session = screenscraper.Session(
        config(min_interval_seconds=0),
        screenscraper.credentials(config(), CREDENTIALS),
        lambda url, headers, timeout: (430, b"quota"),
    )
    with pytest.raises(screenscraper.LookupError_, match="quota"):
        session.request({})
    with pytest.raises(screenscraper.LookupError_):
        session.request({})


# In a scan -----------------------------------------------------------------------------


class FakeScreenScraper:
    def __init__(self, answers=None):
        self.answers = answers or {}
        self.asked = []

    def __call__(self, url, headers, timeout):
        sha1 = url.split("sha1=")[1].split("&")[0]
        self.asked.append(url)
        if sha1 in self.answers:
            return HTTPStatus.OK, json.dumps(self.answers[sha1]).encode()
        return HTTPStatus.NOT_FOUND, b"Erreur : Rom/Iso/Dossier non trouvee !"


def test_screenscraper_is_off_without_the_switch_and_identifies_with_it(
    env,  # noqa: F811
    monkeypatch,
):
    for key, value in CREDENTIALS.items():
        monkeypatch.setenv(key, value)
    fake = FakeScreenScraper()
    *_, folder_scanner = env
    folder_scanner.screenscraper_get = fake
    conn, _ = scan(env)
    assert fake.asked == []

    sha1 = loose_sha1(conn)
    fake.answers[sha1] = game(rom("Known (USA).nes", sha1=sha1))
    conn, result = scan(env, screenscraper=True)
    assert result["status"] == "done" and len(fake.asked) == 1
    assert "romtaille=" in fake.asked[0] and "romnom" not in fake.asked[0]
    method = conn.execute("SELECT method FROM identity WHERE rel_path = ?", (LOOSE,)).fetchone()
    assert method[0] == scanner.METHOD_SCREENSCRAPER


def test_a_name_only_answer_becomes_a_suggestion(env, monkeypatch):  # noqa: F811
    for key, value in CREDENTIALS.items():
        monkeypatch.setenv(key, value)
    fake = FakeScreenScraper()
    *_, folder_scanner = env
    folder_scanner.screenscraper_get = fake
    conn, _ = scan(env)
    sha1 = loose_sha1(conn)
    fake.answers[sha1] = game(rom("Reheadered (J).nes", sha1=sha1))
    conn, _ = scan(env, screenscraper=True)
    (row,) = unmatched.rows(conn, "nes", False, True)
    assert row["screenscraper"]["status"] == screenscraper.NOT_IN_DAT
    assert "Reheadered (J)" in row["screenscraper"]["detail"]
    assert row["suggestions"][0]["game_name"] == "Reheadered (Japan)"


def test_without_credentials_screenscraper_cannot_be_switched_on(make_settings):
    from fastapi.testclient import TestClient

    from g1r.web.app import create_app

    with TestClient(create_app(make_settings())) as client:
        refused = client.put("/api/settings/lookups", json={"screenscraper": True})
        assert refused.status_code == HTTPStatus.BAD_REQUEST
        info = client.get("/api/settings").json()["screenscraper"]
        assert info["configured"] is False and "nes" in info["platforms"]
