"""Matching the subfolders of a folder to platforms ("Add sets from a folder").

Exact names only, never a guess: a subfolder matches a platform when its name, lowercased
with everything but letters and digits removed, equals the same reduction of the platform's
id, short name, name, DAT name or one of its aliases (RomM, ES-DE and Batocera folder
names). A name two platforms would claim matches neither; the user picks.
"""

import re
from dataclasses import dataclass

from g1r.config import PlatformProfile

_NOT_ALNUM = re.compile(r"[^0-9a-z]+")


def key(name: str) -> str:
    return _NOT_ALNUM.sub("", name.lower())


@dataclass(frozen=True)
class Match:
    platform: str | None
    # Why it is (not) matched, as the table shows it.
    note: str


class Matcher:
    def __init__(self, profiles: dict[str, PlatformProfile], unsupported: dict[str, str]):
        claims: dict[str, set[str]] = {}
        for platform_id, p in profiles.items():
            for name in (platform_id, p.short, p.name, p.dat_name, *p.aliases):
                if key(name):
                    claims.setdefault(key(name), set()).add(platform_id)
        self.index = {k: next(iter(v)) for k, v in claims.items() if len(v) == 1}
        self.ambiguous = {k: sorted(v) for k, v in claims.items() if len(v) > 1}
        self.unsupported = {key(k): v for k, v in unsupported.items()}
        self.names = {platform_id: p.name for platform_id, p in profiles.items()}

    def match(self, folder_name: str) -> Match:
        k = key(folder_name)
        if k in self.index:
            return Match(self.index[k], f"matched by its name ({self.names[self.index[k]]})")
        if k in self.ambiguous:
            names = " or ".join(self.names[p] for p in self.ambiguous[k])
            return Match(None, f"could be {names}: pick one")
        if k in self.unsupported:
            return Match(None, f"{self.unsupported[k]} is not supported yet")
        return Match(None, "no platform has this name: pick one or skip it")
