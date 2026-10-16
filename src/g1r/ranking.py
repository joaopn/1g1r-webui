"""Picking the version to keep: strict, so 'undecided' is a normal outcome.

Each enabled criterion gives every version a sortable key (lower is better). The versions
with the best keys on all criteria, in order, are the candidates; exactly one means a
decision, more than one means undecided. There is no alphabetical tiebreak.
"""

from dataclasses import dataclass
from functools import total_ordering

from g1r.config import RankingConfig
from g1r.grouping import Group, Version
from g1r.names import revision_key

LABELS = {
    "prerelease": "full release over pre-release",
    "region": "region priority",
    "language": "language priority",
    "revision": "newest revision",
    "original": "original over re-release",
}


@dataclass
class Decision:
    winner: Version | None
    candidates: list[Version]
    reason: str


@total_ordering
class _Newest:
    """Wraps a revision key so that a newer revision sorts first (lower is better)."""

    def __init__(self, key: tuple):
        self.key = key

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Newest) and self.key == other.key

    def __lt__(self, other: "_Newest") -> bool:
        return self.key > other.key

    def __hash__(self) -> int:
        return hash(self.key)


def _region_key(version: Version, ranking: RankingConfig) -> int:
    order = {r.lower(): i for i, r in enumerate(ranking.regions)}
    unlisted = len(order)
    ranks = [order.get(r.lower(), unlisted) for r in version.parsed.regions] or [unlisted]
    return ranks[0] if ranking.multi_region == "first" else min(ranks)


def _language_key(version: Version, ranking: RankingConfig) -> int:
    order = {lang.lower(): i for i, lang in enumerate(ranking.languages)}
    unlisted = len(order)
    return min(
        [order.get(lang.lower(), unlisted) for lang in version.parsed.languages] or [unlisted]
    )


def criterion_key(name: str, version: Version, ranking: RankingConfig):
    parsed = version.parsed
    if name == "prerelease":
        return int(parsed.prerelease)
    if name == "region":
        return _region_key(version, ranking)
    if name == "language":
        return _language_key(version, ranking)
    if name == "revision":
        return _Newest(revision_key(parsed.revision))
    if name == "original":
        return int(parsed.rerelease)
    raise ValueError(name)


def decide(group: Group, ranking: RankingConfig) -> Decision:
    candidates = list(group.versions)
    if len(candidates) == 1:
        return Decision(candidates[0], candidates, "only version")
    deciding = None
    for name in ranking.criteria:
        best = min(criterion_key(name, v, ranking) for v in candidates)
        narrowed = [v for v in candidates if criterion_key(name, v, ranking) == best]
        if len(narrowed) < len(candidates):
            deciding = name
        candidates = narrowed
        if len(candidates) == 1:
            return Decision(candidates[0], candidates, LABELS[name])
    if deciding is None:
        reason = "enabled criteria do not separate these versions"
    else:
        reason = f"still tied after {LABELS[deciding]}"
    return Decision(None, candidates, reason)
