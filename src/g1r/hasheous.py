"""Hasheous: identify a file by its content hashes (identification step 3, opt-in).

Only the hashes are sent. Answers are cached by SHA1; a "not found" is asked again after
`lookups.hasheous.not_found_ttl_days`. An answer identifies a file only when it comes from
a configured source and its system is the folder's platform.
"""

import json
import sqlite3
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http import HTTPStatus

from g1r.config import Settings
from g1r.hashing import ContentHash

SERVICE = "hasheous"

FOUND = "found"
NOT_FOUND = "not found"
OTHER_PLATFORM = "other platform"
ERROR = "error"


# (url, json body, headers, timeout) -> (HTTP status, body bytes)
Post = Callable[[str, bytes, dict, float], tuple[int, bytes]]


class LookupError_(RuntimeError):
    """The service could not be asked; the file stays unmatched."""


@dataclass(frozen=True)
class Answer:
    status: str
    game_name: str | None = None
    detail: str = ""


def http_post(url: str, body: bytes, headers: dict, timeout: float) -> tuple[int, bytes]:
    request = urllib.request.Request(url, body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LookupError_(f"Hasheous could not be reached: {exc}") from exc


def _fresh(row: sqlite3.Row, ttl_days: float) -> bool:
    if row["found"]:
        return True
    fetched = datetime.strptime(row["fetched_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    return datetime.now(UTC) - fetched < timedelta(days=ttl_days)


def _ask(settings: Settings, conn, h: ContentHash, post: Post, refresh: bool) -> dict | None:
    config = settings.lookups.hasheous
    cached = conn.execute(
        "SELECT * FROM lookup_cache WHERE service = ? AND sha1 = ?", (SERVICE, h.sha1)
    ).fetchone()
    if (
        cached
        and _fresh(cached, config.not_found_ttl_days)
        and not (refresh and not cached["found"])
    ):
        return json.loads(cached["body"]) if cached["found"] else None
    body = json.dumps({"crc": h.crc32, "md5": h.md5, "sha1": h.sha1}).encode()
    headers = {"Content-Type": "application/json", "User-Agent": config.user_agent}
    status, answer = post(config.url, body, headers, config.timeout_seconds)
    if status == HTTPStatus.NOT_FOUND:
        parsed = None
    elif HTTPStatus.OK <= status < HTTPStatus.MULTIPLE_CHOICES:
        try:
            parsed = json.loads(answer)
        except ValueError as exc:
            raise LookupError_("Hasheous sent an answer that is not JSON") from exc
    else:
        raise LookupError_(f"Hasheous answered HTTP {status}")
    conn.execute(
        "INSERT OR REPLACE INTO lookup_cache (service, sha1, found, body) VALUES (?, ?, ?, ?)",
        (SERVICE, h.sha1, parsed is not None, json.dumps(parsed) if parsed else None),
    )
    return parsed


def entry_name(entry: dict) -> str | None:
    """The DAT name of a signature entry: the game's description, else the ROM's name."""
    game = entry.get("game") or {}
    if game.get("description"):
        return game["description"]
    rom_name = (entry.get("rom") or {}).get("name") or ""
    return rom_name.rsplit(".", 1)[0] or None


def same_system(system: str, dat_name: str) -> bool:
    """`Nintendo - Game Boy (Parent-Clone)` is Game Boy; `Nintendo - Game Boy Advance` is not."""
    return system == dat_name or system.startswith(f"{dat_name} (")


def read_answer(settings: Settings, answer: dict, dat_name: str) -> Answer:
    signatures = answer.get("signatures") or {}
    elsewhere: list[str] = []
    for source, label in settings.lookups.hasheous.sources.items():
        for entry in signatures.get(source) or []:
            system = (entry.get("game") or {}).get("system") or ""
            name = entry_name(entry)
            if not name:
                continue
            if same_system(system, dat_name):
                return Answer(FOUND, name, label)
            elsewhere.append(system)
    if elsewhere:
        return Answer(OTHER_PLATFORM, None, f"known for {elsewhere[0]}")
    return Answer(NOT_FOUND)


def lookup(
    settings: Settings,
    conn: sqlite3.Connection,
    hashes: list[ContentHash],
    dat_name: str,
    post: Post,
    *,
    refresh: bool = False,
) -> Answer:
    """The best answer over a file's hashes: found beats other platform beats not found."""
    best = Answer(NOT_FOUND)
    for h in hashes:
        answer = _ask(settings, conn, h, post, refresh)
        if answer is None:
            continue
        result = read_answer(settings, answer, dat_name)
        if result.status == FOUND:
            return result
        if result.status == OTHER_PLATFORM:
            best = result
    return best
