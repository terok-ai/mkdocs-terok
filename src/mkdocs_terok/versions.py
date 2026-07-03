# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: 0BSD

"""Versioned documentation trees for terok-* GitHub Pages sites.

Every PyPI release of a terok repo keeps a frozen docs snapshot under
``/<minor>/`` on the repo's ``gh-pages`` branch, while each master merge
refreshes ``/dev/``.  The Material version chooser is driven purely by a
``versions.json`` file at the tree root — the layout contract established
by `mike <https://github.com/jimporter/mike>`_.  mike itself cannot drive
ProperDocs builds (it shells out to ``mkdocs``), so this module maintains
the same tree layout directly: install a freshly built ``site/`` into its
version directory, upsert the ``versions.json`` entry, re-materialise
aliases (``latest``), and keep the root redirect aimed at the right
default.

The tree lives on ``gh-pages`` and is pushed by the
``publish-versioned-docs.yml`` reusable workflow, which runs this module
from the calling repo's locked docs environment (the same contract as
[`mkdocs_terok.inventory`][]).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from collections.abc import Sequence
from pathlib import Path

_VERSIONS_FILE = "versions.json"

#: Version and alias names become directory names inside the tree, so they
#: must be single path components — no separators, no leading dot (which
#: also rules out ``..``).
_SAFE_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")

_ROOT_REDIRECT = """\
<!DOCTYPE html>
<html>
<head>
<meta http-equiv="refresh" content="0; url={target}/">
<link rel="canonical" href="{target}/">
<title>Redirecting…</title>
</head>
<body>Redirecting to <a href="{target}/">{target}</a>…</body>
</html>
"""


def deploy(
    *,
    site: Path,
    tree: Path,
    version: str,
    title: str | None = None,
    aliases: Sequence[str] = (),
) -> None:
    """Install a built ``site/`` as *version* inside the docs *tree*.

    The chooser entry for *version* is created or replaced; any alias in
    *aliases* is taken over from whichever entry held it before.

    Args:
        site: Freshly built ProperDocs output directory.
        tree: Root of the versioned docs tree (a ``gh-pages`` checkout).
        version: Directory name and chooser identity — a minor release
            like ``0.8``, or ``dev``.
        title: Chooser label; releases pass the full version
            (``0.8.2``).  Defaults to *version*.
        aliases: Alias directories re-pointed at this version
            (typically ``latest``).

    Raises:
        ValueError: *version* or an alias is not a plain directory name
            (path separators, a leading dot, or empty), which would let a
            crafted CLI argument write outside the tree.
    """
    version_dir = _tree_dir(tree, version)
    alias_dirs = [_tree_dir(tree, alias) for alias in aliases]
    entries = _upsert(
        _load_entries(tree), version=version, title=title or version, aliases=list(aliases)
    )
    tree.mkdir(parents=True, exist_ok=True)
    _replace_dir(site, version_dir)
    for alias_dir in alias_dirs:
        _replace_dir(version_dir, alias_dir)
    (tree / _VERSIONS_FILE).write_text(json.dumps(entries, indent=2) + "\n")
    (tree / "index.html").write_text(_ROOT_REDIRECT.format(target=_default_target(entries)))
    (tree / ".nojekyll").touch()


def _load_entries(tree: Path) -> list[dict]:
    """Return the chooser entries recorded in *tree*, oldest deploy wins ties."""
    versions_file = tree / _VERSIONS_FILE
    if not versions_file.is_file():
        return []
    return json.loads(versions_file.read_text())


def _upsert(entries: list[dict], *, version: str, title: str, aliases: list[str]) -> list[dict]:
    """Return *entries* with the *version* entry replaced and *aliases* stolen.

    The result is chooser-ordered: ``dev`` first, then releases newest to
    oldest — the order Material renders verbatim.
    """
    others = [entry for entry in entries if entry["version"] != version]
    for entry in others:
        entry["aliases"] = [alias for alias in entry["aliases"] if alias not in aliases]
    merged = [*others, {"version": version, "title": title, "aliases": aliases}]
    return sorted(merged, key=lambda entry: _release_key(entry["version"]), reverse=True)


def _release_key(version: str) -> tuple[float, ...]:
    """Sort key placing non-numeric channels (``dev``) above any release."""
    try:
        return tuple(float(part) for part in version.split("."))
    except ValueError:
        return (float("inf"),)


def _default_target(entries: list[dict]) -> str:
    """Where the tree-root redirect points.

    The latest release when one exists; before the first release, the
    newest entry there is (``dev``).
    """
    if any("latest" in entry["aliases"] for entry in entries):
        return "latest"
    return entries[0]["version"] if entries else "dev"


def _tree_dir(tree: Path, name: str) -> Path:
    """Resolve *name* as a directory directly inside *tree*, or refuse.

    Version and alias names come from CLI arguments and become directory
    names, so anything that isn't a plain path component (separators, a
    leading dot — which also rules out ``..``) is rejected, and the
    resolved path must stay a direct child of the tree.

    Raises:
        ValueError: *name* would land outside (or on) the tree root.
    """
    if not _SAFE_COMPONENT.fullmatch(name):
        raise ValueError(f"unsafe tree directory name: {name!r}")
    candidate = (tree / name).resolve()
    if not candidate.is_relative_to(tree.resolve()) or candidate == tree.resolve():
        raise ValueError(f"unsafe tree directory name: {name!r}")
    return candidate


def _replace_dir(source: Path, target: Path) -> None:
    """Copy *source* over *target*, dropping whatever was there before."""
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)


def _main(argv: list[str] | None = None) -> None:
    """``python -m mkdocs_terok.versions`` entrypoint."""
    parser = argparse.ArgumentParser(
        prog="python -m mkdocs_terok.versions",
        description="Install a built docs site into a versioned gh-pages tree.",
    )
    parser.add_argument("--site", type=Path, required=True, help="Built ProperDocs site directory")
    parser.add_argument("--tree", type=Path, required=True, help="Root of the versioned docs tree")
    parser.add_argument(
        "--version", required=True, help="Version directory and chooser id (e.g. 0.8 or dev)"
    )
    parser.add_argument(
        "--title", default=None, help="Chooser label (e.g. 0.8.2); defaults to --version"
    )
    parser.add_argument(
        "--alias",
        action="append",
        default=[],
        dest="aliases",
        help="Alias directory re-pointed at this version (repeatable, e.g. latest)",
    )
    args = parser.parse_args(argv)
    deploy(
        site=args.site,
        tree=args.tree,
        version=args.version,
        title=args.title,
        aliases=args.aliases,
    )


if __name__ == "__main__":
    _main()
