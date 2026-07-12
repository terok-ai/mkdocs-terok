#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: 0BSD
"""Lint: README's compatible-release pin ↔ ``pyproject.toml``'s fallback version.

The README shows the canonical install snippet — a PEP 735 group entry
with a compatible-release pin (``"mkdocs-terok~=X.Y.0"``) consumers
copy verbatim.  The pip example sits alongside without a version
specifier (always-latest), so only the pin needs lock-stepping with
the package version.

Compares major.minor.  Pre-release suffixes (``0.5.7a5``) compare on
their numeric major.minor only — alpha cycles within the same minor
don't move the pin.  Exits 0 on match, 1 on drift, 2 if the snippet
isn't present (renamed/removed; this lint needs updating).
"""

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
README = ROOT / "README.md"

_PIN_RE = re.compile(r'"mkdocs-terok~=(?P<major>\d+)\.(?P<minor>\d+)(?:\.\d+)?"')


def main() -> int:
    """Compare README caret against pyproject version; print + exit accordingly."""
    pkg_version = tomllib.loads(PYPROJECT.read_text())["tool"]["hatch"]["version"][
        "fallback-version"
    ]
    pkg_major, pkg_minor = pkg_version.split(".")[:2]

    m = _PIN_RE.search(README.read_text())
    if not m:
        print(
            'README has no `"mkdocs-terok~=X.Y.0"` snippet — either the '
            "snippet was renamed/removed or the pin form changed (this "
            "lint enforces the compatible-release form).",
            file=sys.stderr,
        )
        return 2

    if (m["major"], m["minor"]) != (pkg_major, pkg_minor):
        print(
            f"README pins ~={m['major']}.{m['minor']} but pyproject "
            f"declares {pkg_version}.\n"
            f'Fix: change the snippet to `"mkdocs-terok~={pkg_major}.{pkg_minor}.0"`.',
            file=sys.stderr,
        )
        return 1

    print(f"README pin in sync (~={m['major']}.{m['minor']} matches {pkg_version})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
