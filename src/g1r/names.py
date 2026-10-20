"""Reading the tags of names: No-Intro / Redump style, and TOSEC style.

TOSEC names are positional: "Title vX (year)(publisher)(system)(video)(country)(language)
(copyright)(devstatus)(media)[dump flags][more info]". Year, publisher, media ("Disk 1 of
2") and free-form info keep games apart; country, language, version, development status and
dump flags ("[cr FSS]", "[a]", "[!]") tell the versions of one game apart.
"""

import re
from dataclasses import dataclass, field

from g1r.config import NamesConfig, TosecConfig

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
    # TOSEC dump flag codes ("cr", "a", "!"...), each once, in name order, and how far the
    # dump is from a clean one: its flags' ranks, worst first (lower sorts better, so
    # "[cr]" beats "[cr][a]"; every No-Intro name is ()).
    dump_flags: tuple[str, ...] = ()
    dump: tuple[int, ...] = ()

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


def tags(name: str) -> list[tuple[str, str]]:
    """The name's tags in order: ("paren", text) for "(text)", ("bracket", text) for "[text]"."""
    return [
        ("paren", m["paren"].strip())
        if m["paren"] is not None
        else ("bracket", m["bracket"].strip())
        for m in _TAG.finditer(name)
    ]


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


_MERGED_FORMAT = re.compile(r"\s*\{[^{}]*\}$")
_TOSEC_COUNTRIES = re.compile(r"^[A-Z]{2}(?:-[A-Z]{2})*$")
_TOSEC_LANGUAGES = re.compile(r"^[a-z]{2}(?:-[a-z]{2})*$")
_TOSEC_VERSION = re.compile(r"\s+(?P<version>v[0-9][0-9A-Za-z.]*|Rev [0-9A-Z.]+)$")
_TOSEC_FLAG = re.compile(r"^(?P<code>!|[a-z]+?)(?P<number>[0-9]*)(?:\s.*)?$")


def parse_tosec(name: str, config: TosecConfig) -> ParsedName:
    """A TOSEC name: see the module docstring. Tags it does not know keep games apart. A
    trailing "{D64}" is the format the app added when merging DATs (tosec.merge)."""
    name = _MERGED_FORMAT.sub("", name)
    first = _TAG.search(name)
    title = (name[: first.start()] if first else name).strip()
    revision = None
    if match := _TOSEC_VERSION.search(title):
        revision, title = match["version"], title[: match.start()].strip()
    countries = {c.upper(): r for c, r in config.countries.items()}
    flag_codes = {f.lower() for f in config.dump_flag_rank}
    dev = [d.lower() for d in config.prerelease]
    regions: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    prerelease = False
    others: list[str] = []
    flags: list[str] = []
    for match in _TAG.finditer(name):
        if match["paren"] is not None:
            tag = match["paren"].strip()
            if not regions and _TOSEC_COUNTRIES.match(tag):
                regions = tuple(countries.get(c, c) for c in tag.split("-"))
            elif not languages and _TOSEC_LANGUAGES.match(tag):
                languages = tuple(lang.capitalize() for lang in tag.split("-"))
            elif tag.lower() in dev:
                prerelease = True
            elif tag.lower() in (v.lower() for v in config.neutral):
                continue
            else:
                others.append(tag)
        else:
            tag = match["bracket"].strip()
            flag = _TOSEC_FLAG.match(tag)
            if flag and flag["code"].lower() in flag_codes:
                if flag["code"].lower() not in flags:
                    flags.append(flag["code"].lower())
            else:
                others.append(tag)
    ranks = [config.dump_flag_rank[f] for f in flags]
    return ParsedName(
        name,
        title,
        regions,
        languages,
        revision,
        prerelease,
        False,
        tuple(others),
        tuple(flags),
        tuple(sorted(ranks, reverse=True)) if ranks else (config.clean_rank,),
    )
