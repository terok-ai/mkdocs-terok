# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: 0BSD

"""Tests for the versioned docs tree maintainer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mkdocs_terok.versions import _main, deploy


@pytest.fixture
def site(tmp_path: Path) -> Path:
    """A minimal built site: an index page and a nested asset."""
    built = tmp_path / "site"
    (built / "assets").mkdir(parents=True)
    (built / "index.html").write_text("<h1>built docs</h1>")
    (built / "assets" / "extra.css").write_text("body {}")
    return built


def _entries(tree: Path) -> list[dict]:
    return json.loads((tree / "versions.json").read_text())


class TestDeploy:
    """Verify the gh-pages tree layout after deploys."""

    def test_first_dev_deploy_creates_tree(self, site: Path, tmp_path: Path) -> None:
        """A dev deploy into an empty tree yields dev/, versions.json and a dev redirect."""
        tree = tmp_path / "tree"
        deploy(site=site, tree=tree, version="dev")

        assert (tree / "dev" / "index.html").read_text() == "<h1>built docs</h1>"
        assert (tree / "dev" / "assets" / "extra.css").is_file()
        assert _entries(tree) == [{"version": "dev", "title": "dev", "aliases": []}]
        assert "url=dev/" in (tree / "index.html").read_text()
        assert (tree / ".nojekyll").is_file()

    def test_release_takes_over_root_redirect(self, site: Path, tmp_path: Path) -> None:
        """Once a release holds the latest alias, the root redirect leaves dev."""
        tree = tmp_path / "tree"
        deploy(site=site, tree=tree, version="dev")
        deploy(site=site, tree=tree, version="0.8", title="0.8.0", aliases=["latest"])

        assert (tree / "0.8" / "index.html").is_file()
        assert (tree / "latest" / "index.html").is_file()
        assert "url=latest/" in (tree / "index.html").read_text()

    def test_chooser_order_is_dev_then_newest(self, site: Path, tmp_path: Path) -> None:
        """Entries render dev first, then releases newest to oldest."""
        tree = tmp_path / "tree"
        deploy(site=site, tree=tree, version="0.8", title="0.8.2", aliases=["latest"])
        deploy(site=site, tree=tree, version="0.10", title="0.10.0", aliases=["latest"])
        deploy(site=site, tree=tree, version="0.9", title="0.9.1")
        deploy(site=site, tree=tree, version="dev")

        assert [entry["version"] for entry in _entries(tree)] == ["dev", "0.10", "0.9", "0.8"]

    def test_alias_is_stolen_from_previous_release(self, site: Path, tmp_path: Path) -> None:
        """Deploying a newer release moves the latest alias entry and directory."""
        tree = tmp_path / "tree"
        deploy(site=site, tree=tree, version="0.8", title="0.8.0", aliases=["latest"])
        (site / "index.html").write_text("<h1>0.9 docs</h1>")
        deploy(site=site, tree=tree, version="0.9", title="0.9.0", aliases=["latest"])

        by_version = {entry["version"]: entry for entry in _entries(tree)}
        assert by_version["0.8"]["aliases"] == []
        assert by_version["0.9"]["aliases"] == ["latest"]
        assert (tree / "latest" / "index.html").read_text() == "<h1>0.9 docs</h1>"

    def test_patch_redeploy_replaces_minor_in_place(self, site: Path, tmp_path: Path) -> None:
        """A patch release refreshes its minor directory and chooser title."""
        tree = tmp_path / "tree"
        deploy(site=site, tree=tree, version="0.8", title="0.8.0", aliases=["latest"])
        (site / "index.html").write_text("<h1>0.8.1 docs</h1>")
        deploy(site=site, tree=tree, version="0.8", title="0.8.1", aliases=["latest"])

        assert [entry["title"] for entry in _entries(tree)] == ["0.8.1"]
        assert (tree / "0.8" / "index.html").read_text() == "<h1>0.8.1 docs</h1>"

    @pytest.mark.parametrize("name", ["../escape", "a/b", "..", ".hidden", ""])
    def test_rejects_unsafe_directory_names(self, site: Path, tmp_path: Path, name: str) -> None:
        """Version and alias names must be plain directory names — no traversal."""
        tree = tmp_path / "tree"
        with pytest.raises(ValueError, match="unsafe tree directory name"):
            deploy(site=site, tree=tree, version=name)
        with pytest.raises(ValueError, match="unsafe tree directory name"):
            deploy(site=site, tree=tree, version="0.8", aliases=[name])

    def test_refuses_a_tree_that_is_not_a_docs_tree(self, site: Path, tmp_path: Path) -> None:
        """A non-empty --tree without the versions.json marker must not be touched."""
        not_a_tree = tmp_path / "home"
        (not_a_tree / "Documents").mkdir(parents=True)
        (not_a_tree / "Documents" / "thesis.txt").write_text("precious")

        with pytest.raises(ValueError, match="not a versioned docs tree"):
            deploy(site=site, tree=not_a_tree, version="Documents")

        assert (not_a_tree / "Documents" / "thesis.txt").read_text() == "precious"

    def test_stale_version_files_are_dropped(self, site: Path, tmp_path: Path) -> None:
        """Redeploying a version removes files the new build no longer produces."""
        tree = tmp_path / "tree"
        deploy(site=site, tree=tree, version="dev")
        (site / "assets" / "extra.css").unlink()
        deploy(site=site, tree=tree, version="dev")

        assert not (tree / "dev" / "assets" / "extra.css").exists()


class TestMain:
    """Verify the module CLI drives a deploy."""

    def test_cli_deploys_with_alias(self, site: Path, tmp_path: Path) -> None:
        """The argparse front-end forwards site, tree, version, title and aliases."""
        tree = tmp_path / "tree"
        _main(
            [
                "--site",
                str(site),
                "--tree",
                str(tree),
                "--version",
                "0.8",
                "--title",
                "0.8.2",
                "--alias",
                "latest",
            ]
        )

        assert _entries(tree) == [{"version": "0.8", "title": "0.8.2", "aliases": ["latest"]}]
        assert (tree / "latest" / "index.html").is_file()
