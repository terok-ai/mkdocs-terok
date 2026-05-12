# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: 0BSD

"""Sibling-decoupled ``objects.inv`` builder for terok-* repos.

Each terok repo's docs build references symbols from its siblings via
mkdocstrings ``inventories:`` URLs.  When every repo's strict build needs
every other repo's inventory, a brand-new repo (or a sibling whose Pages
deploy is mid-rebuild) breaks the cycle for everybody.

This module produces a ``objects.inv`` for the *current* repo without
needing any sibling's inventory to exist: it loads the project's
``properdocs.yml``, drops every inventory URL pointing at another
``terok-*`` artifact, then runs a non-strict ``properdocs build`` into a
scratch directory and copies the resulting ``site/objects.inv`` to the
caller's chosen output path.

The output is published independently of the docs site (via the
``terok-ai/docs-inventories`` Contents-API bucket — see
``.github/workflows/publish-inventory.yml``), so the strict docs build of
every repo can fetch a fresh sibling inventory regardless of where the
sibling's own docs deploy is in its lifecycle.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

#: Lines whose inventory URL matches this regex are stripped before the
#: inventory build runs.  Both the legacy GitHub Pages location and the new
#: ``docs-inventories`` raw URL are removed, so a brand-new repo can publish
#: its first inventory before any sibling's bucket file exists.
_SIBLING_INVENTORY_URL = re.compile(
    r"https?://(?:"
    r"terok-ai\.github\.io/(?:terok|terok-[a-z]+|mkdocs-terok)/"
    r"|"
    r"raw\.githubusercontent\.com/terok-ai/docs-inventories/"
    r")"
)

#: Matches a YAML list item whose value is a sibling inventory URL,
#: e.g. ``    - https://terok-ai.github.io/terok-sandbox/objects.inv``.
#: Anchored on ``- `` so plain dependency-list URLs elsewhere in the
#: file (which never start with ``- ``) are left untouched.
_INVENTORY_LINE = re.compile(rf"^\s*-\s+{_SIBLING_INVENTORY_URL.pattern}\S*\s*$")


def build_inventory(*, config: Path, output: Path) -> None:
    """Generate ``objects.inv`` for the project at *config*.

    Loads *config* as text, removes sibling-terok inventory list entries,
    writes the patched config to a scratch directory, runs ``properdocs
    build --no-strict`` into that scratch ``site/`` directory, then copies
    ``site/objects.inv`` to *output*.

    Raises [`SystemExit`][] non-zero if the build fails or the inventory
    file is not produced.
    """
    patched_text = _strip_sibling_inventory_lines(config.read_text())

    # ProperDocs resolves ``docs_dir`` and other relative paths against the
    # config file's *location*, so the patched copy must live next to the
    # original — a remote tmpdir would break ``docs/``, ``mkdocs_terok``
    # script paths, etc.  Use ``NamedTemporaryFile`` with ``delete=False``
    # so the path is unique (no clash with concurrent builds) and clean up
    # explicitly via try/finally.
    config_dir = config.parent.resolve()
    with tempfile.NamedTemporaryFile(
        mode="w",
        prefix=".inventory-",
        suffix=".yml",
        dir=config_dir,
        delete=False,
    ) as patched_file:
        patched_file.write(patched_text)
        patched_path = Path(patched_file.name)

    try:
        with tempfile.TemporaryDirectory(prefix="mkdocs-terok-inventory-") as tmp:
            site_dir = Path(tmp) / "site"
            result = subprocess.run(
                [
                    "properdocs",
                    "build",
                    "--no-strict",
                    "--config-file",
                    str(patched_path),
                    "--site-dir",
                    str(site_dir),
                ],
                check=False,
            )
            if result.returncode != 0:
                print(
                    f"properdocs build failed with exit code {result.returncode}",
                    file=sys.stderr,
                )
                sys.exit(result.returncode)

            produced = site_dir / "objects.inv"
            if not produced.is_file():
                print(
                    f"objects.inv was not produced at {produced}",
                    file=sys.stderr,
                )
                sys.exit(1)

            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(produced, output)
    finally:
        patched_path.unlink(missing_ok=True)


def _strip_sibling_inventory_lines(text: str) -> str:
    """Return *text* with sibling-terok inventory list lines removed.

    Operates on the raw YAML text rather than parsing+re-emitting because
    ProperDocs configs use ``!!python/name:`` tags which round-trip
    poorly through PyYAML's safe loader/dumper pair.  Sibling inventory
    entries always live on their own list-item line, so a line-based
    filter is sufficient and keeps every other line byte-for-byte.
    """
    return "\n".join(line for line in text.splitlines() if not _INVENTORY_LINE.match(line)) + (
        "\n" if text.endswith("\n") else ""
    )


def _main(argv: list[str] | None = None) -> None:
    """``python -m mkdocs_terok.inventory`` entrypoint."""
    parser = argparse.ArgumentParser(
        prog="python -m mkdocs_terok.inventory",
        description="Build a sibling-decoupled objects.inv for a terok-* repo.",
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=Path("properdocs.yml"),
        help="Path to the project's ProperDocs config (default: properdocs.yml)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("objects.inv"),
        help="Where to write the generated inventory (default: ./objects.inv)",
    )
    args = parser.parse_args(argv)
    build_inventory(config=args.config, output=args.output)


if __name__ == "__main__":
    _main()
