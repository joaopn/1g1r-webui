"""Waiting in tests for a folder's background work: poll until it is no longer running,
sleeping between polls, within a time budget, so a slow run is not cut short."""

import time

# Long enough for a real chdman conversion on a slow machine; a hang still fails.
BUDGET_SECONDS = 120
POLL_SECONDS = 0.01


def finished(client, label: str, kind: str = "scan") -> dict:
    """The folder's latest `kind` (scan: a check or a scan; run: an apply, conversion or
    restore) once it is no longer running."""
    deadline = time.monotonic() + BUDGET_SECONDS
    while True:
        body = client.get(f"/api/folders/{label}/{kind}").json()
        if body and body["status"] != "running":
            return body
        if time.monotonic() > deadline:
            raise AssertionError(f"the {kind} of {label} did not finish")
        time.sleep(POLL_SECONDS)
