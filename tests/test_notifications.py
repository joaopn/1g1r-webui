from http import HTTPStatus

from g1r import db, journal, notifications

from .test_api import scanned, setup  # noqa: F401


def insert_run(conn, label, kind, scope, status, started="2026-10-21T10:00:00Z", message=""):
    return conn.execute(
        "INSERT INTO apply_run (folder_label, kind, scope, status, total, message, started_at) "
        "VALUES (?, ?, ?, ?, 2, ?, ?)",
        (label, kind, scope, status, message, started),
    ).lastrowid


def test_feed_names_each_run_and_puts_the_newest_first(make_settings):
    conn = db.open_database(make_settings())
    insert_run(conn, "a", journal.APPLY, journal.CONVERT, "done", "2026-10-21T10:00:01Z")
    insert_run(conn, "a", journal.APPLY, "", "failed", "2026-10-21T10:00:02Z", "1 failed")
    insert_run(conn, "a", journal.APPLY, "Contra", "done", "2026-10-21T10:00:03Z")
    insert_run(conn, "b", journal.APPLY, journal.SCOPE_UNMATCHED, "done", "2026-10-21T10:00:04Z")
    insert_run(conn, "b", journal.APPLY, journal.SCOPE_EMPTY, "done", "2026-10-21T10:00:05Z")
    insert_run(conn, "b", journal.RESTORE, "", "running", "2026-10-21T10:00:06Z")
    conn.execute(
        "INSERT INTO scan (folder_label, status, started_at, message) "
        "VALUES ('c', 'done', '2026-10-21T10:00:07Z', '3 files identified')"
    )
    items = notifications.feed(conn, 10)
    assert [i["kind"] for i in items] == [
        notifications.SCAN,
        journal.RESTORE,
        journal.SCOPE_EMPTY,
        journal.SCOPE_UNMATCHED,
        notifications.APPLY_1G1R,
        notifications.APPLY_1G1R,
        notifications.CONVERSION,
    ]
    assert items[0]["message"] == "3 files identified" and items[0]["id"].startswith("scan-")
    assert items[5]["status"] == "failed" and items[5]["message"] == "1 failed"
    assert len(notifications.feed(conn, 3)) == 3


def test_same_second_rows_keep_their_order(make_settings):
    conn = db.open_database(make_settings())
    first = insert_run(conn, "a", journal.APPLY, "", "done")
    second = insert_run(conn, "a", journal.APPLY, "", "done")
    assert [i["id"] for i in notifications.feed(conn, 10)] == [f"run-{second}", f"run-{first}"]


def test_clear_keeps_running_items(make_settings):
    conn = db.open_database(make_settings())
    done = insert_run(conn, "a", journal.APPLY, "", "done")
    running = insert_run(conn, "a", journal.APPLY, "", "running")
    conn.execute("INSERT INTO scan (folder_label, status) VALUES ('a', 'failed')")
    assert notifications.clear(conn) == 2
    assert [i["id"] for i in notifications.feed(conn, 10)] == [f"run-{running}"]
    # Once it finishes it is listed until cleared again.
    conn.execute("UPDATE apply_run SET status = 'done' WHERE id = ?", (running,))
    assert notifications.clear(conn, f"run-{running}") == 1
    assert notifications.clear(conn, f"run-{done}") == 0
    assert notifications.feed(conn, 10) == []


def test_api_lists_and_clears(setup):  # noqa: F811
    client, _, _ = setup
    scan = scanned(client)
    items = client.get("/api/notifications").json()
    assert [(i["kind"], i["folder_label"], i["status"]) for i in items] == [
        ("scan", "nes", scan["status"])
    ]
    assert client.delete("/api/notifications/bogus").status_code == HTTPStatus.NOT_FOUND
    assert client.delete(f"/api/notifications/{items[0]['id']}").status_code == (
        HTTPStatus.NO_CONTENT
    )
    assert client.get("/api/notifications").json() == []
    client.post("/api/folders/nes/scan")
    assert client.delete("/api/notifications").status_code == HTTPStatus.NO_CONTENT
