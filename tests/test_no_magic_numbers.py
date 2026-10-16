"""Project rule: no hardcoded magic numbers in application code.

Every tunable value lives in g1r/defaults.yaml (or the user's config.yaml). Application code
may only use 0 and 1 (indices, counters, booleans-as-ints, "first"/"next"). Numbers that are
part of a format rather than a choice (for example a file-format offset) belong in config too,
named, so that every number in the code base has exactly one documented home.
"""

import ast
from pathlib import Path

import g1r

ALLOWED = {0, 1}
SOURCE_ROOT = Path(g1r.__file__).parent


def _numeric_literals(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, int | float | complex)
            and not isinstance(node.value, bool)
            and node.value not in ALLOWED
        ):
            yield node.lineno, node.value


def test_application_code_has_no_magic_numbers():
    offenders = [
        f"{path.relative_to(SOURCE_ROOT.parent)}:{line}: {value!r}"
        for path in sorted(SOURCE_ROOT.rglob("*.py"))
        for line, value in _numeric_literals(path)
    ]
    assert not offenders, "move these values into defaults.yaml:\n" + "\n".join(offenders)
