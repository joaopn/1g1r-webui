"""Name suggestions for files nothing identified. Suggestions only, unless the user sets
an auto-match threshold."""

import re
from difflib import SequenceMatcher
from pathlib import PurePosixPath

from g1r.config import FuzzyConfig

_NON_WORD = re.compile(r"[^0-9a-z]+")


def normalise(name: str) -> str:
    return _NON_WORD.sub(" ", name.lower()).strip()


def file_title(rel_path: str) -> str:
    return PurePosixPath(rel_path).stem


def suggestions(
    config: FuzzyConfig, rel_path: str, dat_names: list[str]
) -> list[tuple[str, float]]:
    """The DAT names closest to the file's name, best first, each with its score (0-1)."""
    if config.max_suggestions == 0:
        return []
    wanted = normalise(file_title(rel_path))
    matcher = SequenceMatcher(autojunk=False)
    matcher.set_seq2(wanted)
    scored = []
    # A DAT may list one name twice (libretro's NES DAT: headered and headerless entries).
    for name in dict.fromkeys(dat_names):
        matcher.set_seq1(normalise(name))
        if (
            matcher.real_quick_ratio() < config.min_score
            or matcher.quick_ratio() < config.min_score
        ):
            continue
        score = matcher.ratio()
        if score >= config.min_score:
            scored.append((name, score))
    scored.sort(key=lambda item: (-item[1], item[0]))
    return scored[: config.max_suggestions]
