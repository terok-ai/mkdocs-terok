#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: 0BSD
"""Lint: README's compatible-release pin ↔ ``pyproject.toml``'s fallback version.

The README shows the canonical install snippet — a PEP 735 group entry
with a compatible-release pin (``"mkdocs-terok~=X.Y.0"``) consumers
copy verbatim.  The pip example sits alongside without a version
specifier (always-latest), so only the pin needs lock-stepping with
the package version.

The pin is consumer-facing, so it tracks *published finals* only: a
pre-release fallback version (``0.8.0a1``) is a cycle-internal state
during which the README keeps advertising the last release — the check
skips, mirroring how prereleases skip the changelog.  On a final
version, compares major.minor.  Exits 0 on match or pre-release skip,
1 on drift, 2 if the snippet isn't present (renamed/removed; this lint
needs updating).

``--write`` syncs instead of checking: on a final version the snippet
is rewritten to ``~=X.Y.0``; on a pre-release it is left alone.  The
release tooling runs this right after bumping the version, so promotion
to a final updates the README in the same release-prep commit.
"""

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
README = ROOT / "README.md"

_PIN_RE = re.compile(r'"mkdocs-terok~=(?P<major>\d+)\.(?P<minor>\d+)(?:\.\d+)?"')
_FINAL_RE = re.compile(r"^(?P<major>\d+)\.(?P<minor>\d+)\.\d+$")


def main(write: bool = False) -> int:
    """Compare (or sync) the README pin against the pyproject version."""
    pkg_version = tomllib.loads(PYPROJECT.read_text())["tool"]["hatch"]["version"][
        "fallback-version"
    ]
    final = _FINAL_RE.match(pkg_version)
    if not final:
        print(f"{pkg_version} is a pre-release — README keeps the last published pin")
        return 0

    readme = README.read_text()
    m = _PIN_RE.search(readme)
    if not m:
        print(
            'README has no `"mkdocs-terok~=X.Y.0"` snippet — either the '
            "snippet was renamed/removed or the pin form changed (this "
            "lint enforces the compatible-release form).",
            file=sys.stderr,
        )
        return 2

    pin = f'"mkdocs-terok~={final["major"]}.{final["minor"]}.0"'
    if (m["major"], m["minor"]) == (final["major"], final["minor"]):
        print(f"README pin in sync (~={m['major']}.{m['minor']} matches {pkg_version})")
        return 0
    if write:
        README.write_text(readme[: m.start()] + pin + readme[m.end() :])
        print(f"README pin updated: ~={m['major']}.{m['minor']} -> {pin}")
        return 0
    print(
        f"README pins ~={m['major']}.{m['minor']} but pyproject "
        f"declares {pkg_version}.\n"
        f"Fix: change the snippet to `{pin}` (or run this script with --write).",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(write="--write" in sys.argv[1:]))
