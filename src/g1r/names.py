"""Reading the tags of No-Intro / Redump style names."""

import re
from dataclasses import dataclass, field

from g1r.config import NamesConfig

_TAG = re.compile(r"\((?P<paren>[^()]*)\)|\[(?P<bracket>[^\[\]]*)\]")
_LANGUAGES = re.compile(r"^[A-Z][a-z](?:-[A-Za-z]+)?(?:,[A-Z][a-z](?:-[A-Za-z]+)?)*$")
_REVISION = re.compile(r"^(?:Rev\s+(?P<rev>[0-9A-Z.]+)|v(?P<ver>[0-9][0-9A-Za-z.]*))$")


@dataclass(frozen=True)
class ParsedName:
    name: str
    title: str
    regions: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    revision: str | None = None
    prerelease: bool = False
    rerelease: bool = False
    other_tags: tuple[str, ...] = field(default=())

    @property
    def tags_label(self) -> str:
        parts = [", ".join(self.regions)] if self.regions else []
        if self.languages:
            parts.append(",".join(self.languages))
        if self.revision:
            parts.append(self.revision)
        return " · ".join(parts)


def revision_key(revision: str | None) -> tuple:
    """Sortable revision: none < Rev 1 < Rev 2 < Rev A < Rev B; v1.1 < v1.10."""
    if not revision:
        return ()
    match = _REVISION.match(revision)
    value = (match["rev"] or match["ver"]) if match else revision
    return tuple((int(p), "") if p.isdigit() else (-1, p) for p in re.split(r"[.]", value))


def parse_name(name: str, config: NamesConfig) -> ParsedName:
    regions_vocab = {r.lower(): r for r in config.regions}
    pre = [t.lower() for t in config.prerelease_tags]
    re_ = [t.lower() for t in config.rerelease_tags]
    first = _TAG.search(name)
    title = (name[: first.start()] if first else name).strip()
    regions: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    revision = None
    prerelease = rerelease = False
    others = []
    for match in _TAG.finditer(name):
        tag = (match["paren"] if match["paren"] is not None else match["bracket"]).strip()
        lowered = tag.lower()
        parts = [p.strip() for p in tag.split(",")]
        if not regions and parts and all(p.lower() in regions_vocab for p in parts):
            regions = tuple(regions_vocab[p.lower()] for p in parts)
        elif not languages and _LANGUAGES.match(tag):
            languages = tuple(parts)
        elif revision is None and _REVISION.match(tag):
            revision = tag
        elif any(lowered == p or lowered.startswith(p + " ") for p in pre):
            prerelease = True
        elif any(r in lowered for r in re_):
            rerelease = True
            others.append(tag)
        else:
            others.append(tag)
    return ParsedName(
        name, title, regions, languages, revision, prerelease, rerelease, tuple(others)
    )
