"""Auto-check: sets with the switch on get a Check files run once their last run is older
than the interval set in Settings -> Advanced (maintainer, 2026-11-06)."""

from http import HTTPStatus

from g1r import autocheck, db, notifications

from .test_api import add_nes, setup  # noqa: F401  (fixture)
from .waits import finished


def connect(settings):
    return db.connect(settings.paths.database_path, settings.database.busy_timeout_ms)


def age_runs(conn, minutes):
    conn.execute(
        "UPDATE scan SET started_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ?)",
        (f"-{minutes} minutes",),
    )


def test_the_switch_is_per_set_and_off_until_turned_on(setup):  # noqa: F811
    client, store, _ = setup
    add_nes(client, label="nes")
    assert client.get("/api/folders").json()[0]["auto_check"] is False
    saved = client.put("/api/folders/nes/auto-check", json={"auto_check": True})
    assert saved.status_code == HTTPStatus.OK and saved.json()["auto_check"] is True
    assert client.get("/api/folders/nes").json()["auto_check"] is True
    assert store.load().folder("nes").auto_check
    missing = client.put("/api/folders/none/auto-check", json={"auto_check": True})
    assert missing.status_code == HTTPStatus.NOT_FOUND


def test_a_set_is_due_once_its_last_run_is_older_than_the_interval(setup):  # noqa: F811
    client, store, settings = setup
    add_nes(client, label="nes")
    conn = connect(settings)
    assert autocheck.due(conn, store) == []  # switched off
    client.put("/api/folders/nes/auto-check", json={"auto_check": True})
    assert autocheck.due(conn, store) == ["nes"]  # never checked
    client.post("/api/folders/nes/check")
    finished(client, "nes")
    assert autocheck.due(conn, store) == []  # checked just now (by hand counts)
    minutes = store.auto_check_minutes(store.load())
    age_runs(conn, minutes + 1)
    assert autocheck.due(conn, store) == ["nes"]
    # A shorter interval set in the UI applies at once.
    age_runs(conn, 1 + 1)
    assert autocheck.due(conn, store) == []
    client.put("/api/settings/auto-check", json={"value": 1})
    assert autocheck.due(conn, store) == ["nes"]
    client.put("/api/folders/nes/hidden", json={"hidden": True})
    assert autocheck.due(conn, store) == []


def test_an_auto_check_runs_a_check_and_is_news_only_when_it_finds_something(
    setup,  # noqa: F811
    roms_root,
):
    client, store, settings = setup
    add_nes(client, label="nes")
    client.put("/api/folders/nes/auto-check", json={"auto_check": True})
    conn = connect(settings)
    jobs = client.app.state.jobs
    assert autocheck.run_due(conn, store, jobs) == ["nes"]
    first = finished(client, "nes")
    assert (first["kind"], first["status"]) == ("check", "done")
    # Busy or just checked: nothing starts.
    assert autocheck.run_due(conn, store, jobs) == []
    # The first check found the files: listed. A second finding nothing is not.
    assert [i["title"] for i in notifications.feed(conn, 10)] == ["Check files"]
    age_runs(conn, store.auto_check_minutes(store.load()) + 1)
    assert autocheck.run_due(conn, store, jobs) == ["nes"]
    assert finished(client, "nes")["changes"] == 0
    assert len(notifications.feed(conn, 10)) == 1
    # A new file makes it news again.
    (roms_root / "NES Set" / "new.nes").write_bytes(b"new")
    age_runs(conn, store.auto_check_minutes(store.load()) + 1)
    autocheck.run_due(conn, store, jobs)
    assert finished(client, "nes")["changes"] == 1
    assert len(notifications.feed(conn, 10)) == 1 + 1
    assert conn.execute("SELECT SUM(auto) FROM scan").fetchone()[0] == 1 + 1 + 1


def test_the_interval_is_set_in_the_ui_within_the_configured_max(setup):  # noqa: F811
    client, store, settings = setup
    auto = settings.jobs.auto_check
    assert client.get("/api/settings").json()["auto_check_minutes"] == {
        "value": auto.minutes,
        "default": auto.minutes,
        "max": auto.max_minutes,
    }
    saved = client.put("/api/settings/auto-check", json={"value": auto.max_minutes}).json()
    assert saved["auto_check_minutes"]["value"] == auto.max_minutes
    too_long = client.put("/api/settings/auto-check", json={"value": auto.max_minutes + 1})
    assert too_long.status_code == HTTPStatus.BAD_REQUEST
    client.put("/api/settings/auto-check", json={"value": None})
    assert store.load().auto_check_minutes is None
