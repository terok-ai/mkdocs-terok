#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: 0BSD
"""Lint: README install snippet's pin ↔ pyproject.toml's version.

The README shows the canonical way to add ``mkdocs-terok`` as a docs-build
dep — a ``mkdocs-terok = "^X.Y"`` Poetry caret pin.  When a new minor
release lands, the README's caret has to move in lockstep; this script
catches the case where ``pyproject.toml`` was bumped but the README was
forgotten (a real foot-gun: every consumer who copies the snippet
straight from GitHub gets the stale spec).

Compares major.minor.  Pre-release suffixes (``0.5.7a5``) compare on
their numeric major.minor only — alpha cycles within the same minor
don't move the caret.  Exits 0 on match, 1 on drift, 2 on
unparseable README / pyproject.
"""

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
README = ROOT / "README.md"

_PIN_RE = re.compile(r'mkdocs-terok\s*=\s*"\^(?P<major>\d+)\.(?P<minor>\d+)(?:\.\d+)?"')


def main() -> int:
    """Compare README pin against pyproject version; print + exit accordingly."""
    pkg_version = tomllib.loads(PYPROJECT.read_text())["tool"]["poetry"]["version"]
    pkg_major, pkg_minor = pkg_version.split(".")[:2]

    m = _PIN_RE.search(README.read_text())
    if not m:
        print(
            'README has no `mkdocs-terok = "^X.Y"` install snippet — '
            "either the snippet was renamed/removed (update this lint) or "
            "the pin format changed (this lint enforces the caret form).",
            file=sys.stderr,
        )
        return 2

    if (m["major"], m["minor"]) != (pkg_major, pkg_minor):
        print(
            f'README install snippet pins ^{m["major"]}.{m["minor"]} but '
            f"pyproject declares {pkg_version}.\n"
            f'Fix: change the snippet to `mkdocs-terok = "^{pkg_major}.{pkg_minor}"`.',
            file=sys.stderr,
        )
        return 1

    print(f"README pin in sync (^{m['major']}.{m['minor']} matches {pkg_version})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
