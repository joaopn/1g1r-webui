"""Hasheous: identify a file by its content hashes (identification step 3, opt-in).

Only the hashes are sent. Answers are cached by SHA1; a "not found" is asked again after
`lookups.hasheous.not_found_ttl_days`. An answer identifies a file only when it comes from
a configured source and its system is the folder's platform.
"""

import json
import sqlite3
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http import HTTPStatus

from g1r.config import Settings
from g1r.hashing import ContentHash
from g1r.names import parse_name

SERVICE = "hasheous"

FOUND = "found"
NOT_FOUND = "not found"
OTHER_PLATFORM = "other platform"
ERROR = "error"
SKIPPED = "skipped"


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


def _names(entry: dict) -> dict[str, str | None]:
    """An entry's two readings of the DAT name: its game's description and its ROM's file
    name without the extension."""
    rom_name = (entry.get("rom") or {}).get("name") or ""
    return {
        "game": (entry.get("game") or {}).get("description") or None,
        "rom": rom_name.rsplit(".", 1)[0] or None,
    }


def best_name(settings: Settings, entries: list[dict], name_from: str) -> str | None:
    """Hasheous's entries disagree (a stale description; a ROM name stripped of its tags), so
    the name is a vote over every reading. Ties go to a name that carries a region (every
    No-Intro and Redump name does), then to the source's configured reading."""
    votes: Counter[str] = Counter()
    preferred: set[str] = set()
    for entry in entries:
        for reading, name in _names(entry).items():
            if name:
                votes[name] += 1
                if reading == name_from:
                    preferred.add(name)
    if not votes:
        return None

    def rank(name: str) -> tuple[int, bool, bool]:
        has_region = bool(parse_name(name, settings.names).regions)
        return votes[name], has_region, name in preferred

    return max(sorted(votes), key=rank)


def same_system(system: str, dat_name: str) -> bool:
    """`Nintendo - Game Boy (Parent-Clone)` is Game Boy; `Nintendo - Game Boy Advance` is not."""
    return system == dat_name or system.startswith(f"{dat_name} (")


def read_answer(settings: Settings, answer: dict, dat_name: str) -> Answer:
    signatures = answer.get("signatures") or {}
    elsewhere: list[str] = []
    for source, config in settings.lookups.hasheous.sources.items():
        mine = []
        for entry in signatures.get(source) or []:
            system = (entry.get("game") or {}).get("system") or ""
            if same_system(system, dat_name):
                mine.append(entry)
            elif system:
                elsewhere.append(system)
        name = best_name(settings, mine, config.name_from)
        if name:
            return Answer(FOUND, name, config.label)
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
