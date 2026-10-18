"""ScreenScraper: identify a file by its content hashes (identification step 4, opt-in).

Only the hashes, the size and the platform's ScreenScraper system id are sent, never a
file name, so an answer is about the data. Even so it identifies a file only when the ROM
it returns has our hash and its file name is an entry of the folder's DAT; ScreenScraper's
own game names are not DAT names, so anything else becomes name suggestions.

Credentials are entered in Settings → Online lookups and kept in a private file in the data
directory (an environment variable overrides a field); they are never sent back to the page
nor shown in Settings → Advanced. Requests are spaced by `min_interval_seconds` and stop for
the scan once the daily quota ScreenScraper reports in each answer is reached.
"""

import json
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from pathlib import Path, PurePosixPath

from g1r.config import ScreenScraperConfig, Settings
from g1r.hashing import ContentHash
from g1r.private_files import write_private

SERVICE = "screenscraper"

FOUND = "found"
NOT_FOUND = "not found"
NOT_IN_DAT = "not in the DAT"
ERROR = "error"
SKIPPED = "skipped"

# (url, headers, timeout) -> (HTTP status, body bytes)
Get = Callable[[str, dict, float], tuple[int, bytes]]

# ScreenScraper's answers that end the lookups for this scan (with its own wording).
STOPPING = {
    HTTPStatus.UNAUTHORIZED: "the API is closed to non-members right now",
    HTTPStatus.FORBIDDEN: "the developer credentials were refused",
    HTTPStatus.LOCKED: "the API is closed right now",
    HTTPStatus.UPGRADE_REQUIRED: "this software was refused (update it)",
    HTTPStatus.TOO_MANY_REQUESTS: "too many requests at once",
}


class LookupError_(RuntimeError):
    """ScreenScraper could not be asked; the rest of the scan's lookups stop."""


@dataclass(frozen=True)
class Credentials:
    devid: str
    devpassword: str
    ssid: str | None
    sspassword: str | None


# The credential fields, as stored and as named in `environment`.
FIELDS = ("devid", "devpassword", "user", "password")
FROM_ENVIRONMENT = "environment"
FROM_APP = "app"


def credentials_path(settings: Settings) -> Path:
    return settings.paths.data_dir / settings.lookups.screenscraper.credentials_file


def stored_credentials(settings: Settings) -> dict[str, str]:
    """What was entered in the app; nothing when the file is missing or unreadable."""
    try:
        data = json.loads(credentials_path(settings).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if k in FIELDS and isinstance(v, str) and v}


def store_credentials(settings: Settings, changes: dict[str, str | None]) -> None:
    """Set the given fields; an empty value removes one."""
    values = stored_credentials(settings)
    for name, value in changes.items():
        if name not in FIELDS:
            raise ValueError(f"unknown credential {name!r}")
        if value:
            values[name] = value
        else:
            values.pop(name, None)
    write_private(
        credentials_path(settings),
        json.dumps(values).encode(),
        settings.lookups.screenscraper.file_mode,
    )


def _values(settings: Settings, environ) -> dict[str, tuple[str, str]]:
    """field -> (value, where it comes from): the environment over the app."""
    environ = os.environ if environ is None else environ
    names = settings.lookups.screenscraper.environment.model_dump()
    stored = stored_credentials(settings)
    found = {}
    for name in FIELDS:
        if environ.get(names[name]):
            found[name] = (environ[names[name]], FROM_ENVIRONMENT)
        elif stored.get(name):
            found[name] = (stored[name], FROM_APP)
    return found


def credential_sources(settings: Settings, environ=None) -> dict[str, str | None]:
    """For the settings page: where each field is set, never its value."""
    found = _values(settings, environ)
    return {name: found[name][1] if name in found else None for name in FIELDS}


def credentials(settings: Settings, environ=None) -> Credentials | None:
    """The developer credentials (required) and the user account (optional)."""
    found = {name: value for name, (value, _) in _values(settings, environ).items()}
    if not found.get("devid") or not found.get("devpassword"):
        return None
    return Credentials(
        found["devid"], found["devpassword"], found.get("user"), found.get("password")
    )


@dataclass(frozen=True)
class Answer:
    status: str
    game_name: str | None = None
    detail: str = ""
    # ScreenScraper's name for the file when it is no DAT entry: becomes name suggestions.
    known_as: str | None = None


@dataclass
class Session:
    """One scan's lookups: spacing between requests, and the quota the answers report."""

    config: ScreenScraperConfig
    creds: Credentials
    get: Get
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    last: float | None = None
    quota_left: int | None = None
    stopped: str | None = None
    asked: int = field(default=0)

    def request(self, params: dict) -> tuple[int, bytes]:
        if self.stopped:
            raise LookupError_(self.stopped)
        if self.quota_left is not None and self.quota_left <= self.config.quota_reserve:
            self.stopped = "today's ScreenScraper quota is used up"
            raise LookupError_(self.stopped)
        if self.last is not None:
            wait = self.config.min_interval_seconds - (self.clock() - self.last)
            if wait > 0:
                self.sleep(wait)
        query = {
            "devid": self.creds.devid,
            "devpassword": self.creds.devpassword,
            "softname": self.config.softname,
            "output": "json",
            **({"ssid": self.creds.ssid} if self.creds.ssid else {}),
            **({"sspassword": self.creds.sspassword} if self.creds.sspassword else {}),
            **params,
        }
        url = f"{self.config.url}?{urllib.parse.urlencode(query)}"
        headers = {"User-Agent": self.config.user_agent}
        try:
            status, body = self.get(url, headers, self.config.timeout_seconds)
        finally:
            self.last = self.clock()
            self.asked += 1
        if status in STOPPING:
            self.stopped = f"ScreenScraper: {STOPPING[HTTPStatus(status)]}"
            raise LookupError_(self.stopped)
        if status in self.config.quota_statuses:
            self.stopped = "today's ScreenScraper quota is used up"
            raise LookupError_(self.stopped)
        return status, body

    def note_quota(self, answer: dict) -> None:
        user = (answer.get("response") or {}).get("ssuser") or {}
        try:
            used = int(user.get("requeststoday"))
            allowed = int(user.get("maxrequestsperday"))
        except (TypeError, ValueError):
            return
        self.quota_left = allowed - used


def http_get(url: str, headers: dict, timeout: float) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LookupError_(f"ScreenScraper could not be reached: {exc}") from exc


def _fresh(row: sqlite3.Row, ttl_days: float) -> bool:
    if row["found"]:
        return True
    fetched = datetime.strptime(row["fetched_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    return datetime.now(UTC) - fetched < timedelta(days=ttl_days)


def _ask(session: Session, conn, h: ContentHash, system_id: int, refresh: bool) -> dict | None:
    cached = conn.execute(
        "SELECT * FROM lookup_cache WHERE service = ? AND sha1 = ?", (SERVICE, h.sha1)
    ).fetchone()
    if (
        cached
        and _fresh(cached, session.config.not_found_ttl_days)
        and not (refresh and not cached["found"])
    ):
        return json.loads(cached["body"]) if cached["found"] else None
    status, body = session.request(
        {
            "crc": h.crc32,
            "md5": h.md5,
            "sha1": h.sha1,
            "romtaille": str(h.size),
            "systemeid": str(system_id),
            "romtype": "rom",
        }
    )
    if status == HTTPStatus.NOT_FOUND:
        parsed = None
    elif HTTPStatus.OK <= status < HTTPStatus.MULTIPLE_CHOICES:
        try:
            parsed = json.loads(body)
        except ValueError as exc:
            raise LookupError_("ScreenScraper sent an answer that is not JSON") from exc
        session.note_quota(parsed)
    else:
        raise LookupError_(f"ScreenScraper answered HTTP {status}")
    conn.execute(
        "INSERT OR REPLACE INTO lookup_cache (service, sha1, found, body) VALUES (?, ?, ?, ?)",
        (SERVICE, h.sha1, parsed is not None, json.dumps(parsed) if parsed else None),
    )
    return parsed


def _same_data(rom: dict, h: ContentHash) -> bool:
    """The ROM ScreenScraper returned is ours: equal SHA1, else MD5, else CRC32 and size."""
    for key, ours in (("romsha1", h.sha1), ("rommd5", h.md5)):
        theirs = (rom.get(key) or "").lower()
        if theirs:
            return theirs == ours
    crc = (rom.get("romcrc") or "").lower()
    size = str(rom.get("romsize") or "")
    return bool(crc) and crc == h.crc32 and size == str(h.size)


def read_answer(answer: dict, h: ContentHash, dat_names: set[str]) -> Answer:
    game = (answer.get("response") or {}).get("jeu") or {}
    if not game:
        return Answer(NOT_FOUND)
    roms = [game.get("rom") or {}, *(game.get("roms") or [])]
    ours = [r for r in roms if r and _same_data(r, h)]
    for rom in ours:
        stem = PurePosixPath(rom.get("romfilename") or "").stem
        if stem in dat_names:
            return Answer(FOUND, stem, "ScreenScraper")
    named = next((PurePosixPath(r.get("romfilename") or "").stem for r in ours), None)
    names = game.get("noms") or []
    known = named or next((n.get("text") for n in names if n.get("text")), None)
    detail = f"known as {known}" if known else "known, with no name"
    if not ours:
        detail += " (by a different ROM, not this data)"
    return Answer(NOT_IN_DAT, None, detail, known)


def lookup(
    session: Session,
    conn: sqlite3.Connection,
    hashes: list[ContentHash],
    system_id: int,
    dat_names: set[str],
    *,
    refresh: bool = False,
) -> Answer:
    """The best answer over a file's hashes: found beats a name beats not found."""
    best = Answer(NOT_FOUND)
    for h in hashes:
        answer = _ask(session, conn, h, system_id, refresh)
        if answer is None:
            continue
        result = read_answer(answer, h, dat_names)
        if result.status == FOUND:
            return result
        if result.status == NOT_IN_DAT and best.status == NOT_FOUND:
            best = result
    return best
