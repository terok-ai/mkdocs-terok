#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: 0BSD
"""Lint: README install snippets stay in sync with ``pyproject.toml``'s version.

The README shows three canonical ways to add ``mkdocs-terok`` as a
docs-build dep — Poetry's caret form and PEP 440 ``>=X.Y,<X.Y+1`` bounds
for uv / pip.  When a new minor release lands, every form has to move
in lockstep; this script catches the case where ``pyproject.toml`` was
bumped but the README was forgotten (a real foot-gun: every consumer
who copies the snippet straight from GitHub gets a stale spec).

Compares major.minor for every recognised occurrence.  Pre-release
suffixes (``0.5.7a5``) compare on their numeric major.minor only —
alpha cycles within the same minor don't move the bounds.  Exits 0 on
all-in-sync, 1 on any drift, 2 if the README contains no recognised
snippet at all (renamed/removed; this lint needs updating).
"""

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
README = ROOT / "README.md"

# Two recognised forms; both extract the lower-bound major.minor.
#  - Poetry caret:  mkdocs-terok = "^0.6"   (optional patch suffix ignored)
#  - PEP 440:       mkdocs-terok>=0.6       (optional ",<X.Y" ignored — only
#                                            the lower bound is enforced; that
#                                            is what consumers pin against)
_PATTERNS = [
    re.compile(r'mkdocs-terok\s*=\s*"\^(?P<major>\d+)\.(?P<minor>\d+)(?:\.\d+)?"'),
    re.compile(r"mkdocs-terok>=(?P<major>\d+)\.(?P<minor>\d+)"),
]


def main() -> int:
    """Compare every README occurrence against pyproject version; print + exit."""
    pkg_version = tomllib.loads(PYPROJECT.read_text())["tool"]["poetry"]["version"]
    pkg_major, pkg_minor = pkg_version.split(".")[:2]
    expected = (pkg_major, pkg_minor)

    text = README.read_text()
    matches = [m for pat in _PATTERNS for m in pat.finditer(text)]
    if not matches:
        print(
            "README has no recognised `mkdocs-terok` install snippet — "
            "either the snippet was renamed/removed or its pin form changed "
            "(this lint enforces Poetry caret and PEP 440 `>=X.Y` forms).",
            file=sys.stderr,
        )
        return 2

    drift = [m for m in matches if (m["major"], m["minor"]) != expected]
    if drift:
        snippets = "\n".join(f"  - {m.group(0)}" for m in drift)
        print(
            f"README install snippet(s) out of sync with pyproject "
            f"{pkg_version} (expected major.minor = "
            f"{pkg_major}.{pkg_minor}):\n{snippets}",
            file=sys.stderr,
        )
        return 1

    print(f"README pins in sync ({len(matches)} occurrence(s) match {pkg_version})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
