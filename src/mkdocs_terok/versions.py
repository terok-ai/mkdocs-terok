# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: 0BSD

"""Stateless versioned-docs assembly for terok-* GitHub Pages sites.

Every PyPI release ships its built docs as an immutable release asset
(``docs-site.tar.gz``); the served site is reassembled from scratch on
every deploy: the newest final release of each of the last few minors
plus a fresh ``/dev/`` build, with ``versions.json`` — the contract
Material's version chooser reads — derived from the release list.
Nothing is stored between deploys, so there is no ``gh-pages`` branch to
protect, no history to squash, and a deploy is a pure function of the
release set and master.

Retention is an assembly parameter: only the newest *keep* minors are
served (the chooser and the site plateau instead of growing with the
release cadence); older versions stay downloadable from their release
assets forever.  Root assets — files hotlinked at the site root by
READMEs on GitHub and in immutable PyPI descriptions — are copied out
of the dev build so their well-known URLs survive versioning.

The module is IO-light on purpose: the ``publish-versioned-docs.yml``
reusable workflow fetches the release list and downloads the snapshot
tarballs, while the selection and tree-layout logic lives here, where it
is testable.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

#: Name of the per-release docs snapshot asset.
DOCS_ASSET = "docs-site.tar.gz"

#: Final releases only — alphas never reach PyPI and mint no docs.
_FINAL_TAG = re.compile(r"v(\d+)\.(\d+)\.(\d+)")

#: Minors become directory names inside the tree; anything else in a
#: ``--plan`` file (path separators, ``..``) must not reach a path join.
_MINOR = re.compile(r"\d+\.\d+")

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


def plan(releases: list[dict], *, keep: int) -> list[dict]:
    """Select which release snapshots the served site carries.

    From the GitHub release list, final ``vX.Y.Z`` releases carrying the
    docs asset are grouped by minor; the highest patch wins its minor,
    and the newest *keep* minors survive.

    Args:
        releases: Release objects as returned by the GitHub API
            (``tag_name``, ``draft``, ``assets[].name`` are consulted).
        keep: How many minors to serve.

    Returns:
        Entries ``{"minor", "tag"}``, newest minor first.
    """
    best: dict[tuple[int, int], tuple[int, str]] = {}
    for release in releases:
        match = _FINAL_TAG.fullmatch(release.get("tag_name", ""))
        if not match or release.get("draft"):
            continue
        if not any(asset.get("name") == DOCS_ASSET for asset in release.get("assets", ())):
            continue
        major, minor, patch = (int(part) for part in match.groups())
        if patch >= best.get((major, minor), (-1, ""))[0]:
            best[(major, minor)] = (patch, release["tag_name"])
    newest = sorted(best, reverse=True)[:keep]
    return [
        {"minor": f"{major}.{minor}", "tag": best[(major, minor)][1]} for major, minor in newest
    ]


def assemble(
    *,
    dev_site: Path,
    snapshots: Path,
    entries: list[dict],
    out: Path,
    root_assets: Sequence[str] = (),
) -> None:
    """Lay out the complete site tree for a Pages deploy.

    Consumes its inputs: *dev_site* and the snapshot directories are
    moved into the tree, not copied — they are per-run scratch extracts,
    and a copy would double the whole served site on the deploy path.

    *root_assets* are the site's well-known root URLs: files (READMEs
    hotlink logos from GitHub and immutable PyPI descriptions) that must
    stay reachable at ``<site>/<asset>`` even though the versioned tree
    buries every build under a version directory.  Each is copied from
    the dev build to the same path at the tree root — before the
    assembler writes its own root files, so ``versions.json`` and the
    redirect ``index.html`` can never be shadowed.

    Args:
        dev_site: Freshly built ProperDocs output for master.
        snapshots: Directory holding one unpacked snapshot per served
            minor (``snapshots/<minor>/``), as planned by
            [`plan`][mkdocs_terok.versions.plan].
        entries: The plan — newest minor first.
        out: Tree to create; replaced wholesale if it exists.
        root_assets: Site-relative files to copy from the dev build to
            the tree root.

    Raises:
        ValueError: an entry's ``minor`` is not a plain ``X.Y`` name, a
            root asset is not a plain relative path or is missing from
            the dev build, or *out* points at an existing non-empty
            directory that is not a previously assembled tree
            (mispointed ``--out``).
    """
    for entry in entries:
        if not _MINOR.fullmatch(entry["minor"]):
            raise ValueError(f"unsafe minor in plan: {entry['minor']!r}")
    for asset in root_assets:
        parts = PurePosixPath(asset).parts
        if not parts or parts[0] == "/" or ".." in parts:
            raise ValueError(f"unsafe root asset: {asset!r}")
    _ensure_replaceable(out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    shutil.move(dev_site, out / "dev")
    for asset in root_assets:
        source = out / "dev" / asset
        if not source.is_file():
            raise ValueError(f"root asset missing from the dev build: {asset}")
        (out / asset).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, out / asset)
    for entry in entries:
        shutil.move(snapshots / entry["minor"], out / entry["minor"])
    chooser = [{"version": "dev", "title": "dev", "aliases": []}] + [
        {
            "version": entry["minor"],
            "title": entry["tag"].lstrip("v"),
            "aliases": ["latest"] if entry is entries[0] else [],
        }
        for entry in entries
    ]
    (out / "versions.json").write_text(json.dumps(chooser, indent=2) + "\n")
    target = entries[0]["minor"] if entries else "dev"
    (out / "index.html").write_text(_ROOT_REDIRECT.format(target=target))
    (out / ".nojekyll").touch()


def _ensure_replaceable(out: Path) -> None:
    """Refuse to wipe a directory that isn't an assembled docs tree.

    Assembly replaces *out* wholesale, so a mispointed ``--out`` (a home
    directory, a source checkout) must not cost data: the target must be
    absent, empty (fresh runner temp dir), or carry the
    ``versions.json`` marker from a previous assembly.

    Raises:
        ValueError: *out* exists, is non-empty, and has no marker.
    """
    if not out.exists() or not any(out.iterdir()) or (out / "versions.json").is_file():
        return
    raise ValueError(f"refusing to replace {out}: non-empty and not an assembled docs tree")


def _main(argv: list[str] | None = None) -> None:
    """``python -m mkdocs_terok.versions`` entrypoint (plan / assemble)."""
    parser = argparse.ArgumentParser(
        prog="python -m mkdocs_terok.versions",
        description="Assemble a versioned docs site from release snapshots plus a dev build.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    plan_cmd = commands.add_parser("plan", help="Select served snapshots from the release list")
    plan_cmd.add_argument(
        "--releases", type=Path, required=True, help="GitHub API release list (JSON file)"
    )
    plan_cmd.add_argument(
        "--keep", type=int, default=6, help="How many newest minors to serve (default: 6)"
    )

    assemble_cmd = commands.add_parser("assemble", help="Lay out the site tree for deploy")
    assemble_cmd.add_argument(
        "--dev", type=Path, required=True, help="Built ProperDocs site for master"
    )
    assemble_cmd.add_argument(
        "--snapshots", type=Path, required=True, help="Directory of unpacked snapshots per minor"
    )
    assemble_cmd.add_argument(
        "--plan", type=Path, required=True, help="Plan JSON produced by the plan command"
    )
    assemble_cmd.add_argument(
        "--out", type=Path, required=True, help="Tree to create for upload-pages-artifact"
    )
    assemble_cmd.add_argument(
        "--root-assets",
        nargs="*",
        default=[],
        metavar="PATH",
        help="Site-relative files copied from the dev build to the tree root (well-known URLs)",
    )

    args = parser.parse_args(argv)
    if args.command == "plan":
        print(json.dumps(plan(json.loads(args.releases.read_text()), keep=args.keep), indent=2))
    else:
        assemble(
            dev_site=args.dev,
            snapshots=args.snapshots,
            entries=json.loads(args.plan.read_text()),
            out=args.out,
            root_assets=args.root_assets,
        )


if __name__ == "__main__":
    _main()
