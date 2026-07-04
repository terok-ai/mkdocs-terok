# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: 0BSD

"""Tests for the stateless versioned-docs assembler."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mkdocs_terok.versions import DOCS_ASSET, _main, assemble, plan


def _release(tag: str, *, draft: bool = False, with_asset: bool = True) -> dict:
    assets = [{"name": DOCS_ASSET}] if with_asset else []
    return {"tag_name": tag, "draft": draft, "assets": assets}


class TestPlan:
    """Verify snapshot selection from the GitHub release list."""

    def test_newest_patch_wins_its_minor(self) -> None:
        """Within one minor, only the highest patch is served."""
        entries = plan([_release("v0.8.0"), _release("v0.8.2"), _release("v0.8.1")], keep=6)
        assert entries == [{"minor": "0.8", "tag": "v0.8.2", "title": "0.8.2"}]

    def test_minors_are_newest_first_and_capped(self) -> None:
        """Retention keeps only the newest *keep* minors, newest first."""
        releases = [_release(f"v0.{m}.0") for m in (7, 10, 8, 9)]
        entries = plan(releases, keep=2)
        assert [entry["minor"] for entry in entries] == ["0.10", "0.9"]

    def test_ignores_alphas_drafts_and_assetless_releases(self) -> None:
        """Only final, published releases carrying the docs asset qualify."""
        releases = [
            _release("v0.9.0a1"),
            _release("v0.9.0", draft=True),
            _release("v0.8.0", with_asset=False),
            _release("v0.7.3"),
        ]
        assert [entry["tag"] for entry in plan(releases, keep=6)] == ["v0.7.3"]

    def test_empty_release_list(self) -> None:
        """Before the first release there is nothing to serve."""
        assert plan([], keep=6) == []


class TestAssemble:
    """Verify the deployed tree layout."""

    @pytest.fixture
    def dev_site(self, tmp_path: Path) -> Path:
        """A minimal dev build."""
        built = tmp_path / "dev-site"
        built.mkdir()
        (built / "index.html").write_text("<h1>dev docs</h1>")
        return built

    @pytest.fixture
    def snapshots(self, tmp_path: Path) -> Path:
        """Unpacked snapshots for minors 0.9 and 0.8."""
        root = tmp_path / "snapshots"
        for minor in ("0.9", "0.8"):
            (root / minor).mkdir(parents=True)
            (root / minor / "index.html").write_text(f"<h1>{minor} docs</h1>")
        return root

    def test_tree_layout_and_chooser(self, dev_site: Path, snapshots: Path, tmp_path: Path) -> None:
        """dev + served minors land in the tree; chooser is dev-first with latest label."""
        out = tmp_path / "tree"
        entries = [
            {"minor": "0.9", "tag": "v0.9.1", "title": "0.9.1"},
            {"minor": "0.8", "tag": "v0.8.2", "title": "0.8.2"},
        ]
        assemble(dev_site=dev_site, snapshots=snapshots, entries=entries, out=out)

        assert (out / "dev" / "index.html").read_text() == "<h1>dev docs</h1>"
        assert (out / "0.9" / "index.html").read_text() == "<h1>0.9 docs</h1>"
        assert (out / "0.8" / "index.html").read_text() == "<h1>0.8 docs</h1>"
        assert json.loads((out / "versions.json").read_text()) == [
            {"version": "dev", "title": "dev", "aliases": []},
            {"version": "0.9", "title": "0.9.1", "aliases": ["latest"]},
            {"version": "0.8", "title": "0.8.2", "aliases": []},
        ]
        assert "url=0.9/" in (out / "index.html").read_text()
        assert (out / ".nojekyll").is_file()

    def test_no_releases_serves_dev_only(self, dev_site: Path, tmp_path: Path) -> None:
        """Before the first release the root redirect points at dev."""
        out = tmp_path / "tree"
        assemble(dev_site=dev_site, snapshots=tmp_path / "none", entries=[], out=out)

        assert "url=dev/" in (out / "index.html").read_text()
        assert [e["version"] for e in json.loads((out / "versions.json").read_text())] == ["dev"]

    def test_reassembly_replaces_previous_tree(
        self, dev_site: Path, snapshots: Path, tmp_path: Path
    ) -> None:
        """A deploy is a pure function of its inputs — stale content vanishes."""
        out = tmp_path / "tree"
        entries = [{"minor": "0.9", "tag": "v0.9.1", "title": "0.9.1"}]
        assemble(dev_site=dev_site, snapshots=snapshots, entries=entries, out=out)
        assemble(dev_site=dev_site, snapshots=snapshots, entries=[], out=out)

        assert not (out / "0.9").exists()


class TestMain:
    """Verify the two-command CLI round-trip."""

    def test_plan_then_assemble(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """plan output feeds assemble unchanged."""
        releases = tmp_path / "releases.json"
        releases.write_text(json.dumps([_release("v0.8.1"), _release("v0.8.0")]))
        _main(["plan", "--releases", str(releases), "--keep", "3"])
        plan_json = capsys.readouterr().out
        assert json.loads(plan_json) == [{"minor": "0.8", "tag": "v0.8.1", "title": "0.8.1"}]

        dev = tmp_path / "site"
        dev.mkdir()
        (dev / "index.html").write_text("dev")
        (tmp_path / "snapshots" / "0.8").mkdir(parents=True)
        (tmp_path / "snapshots" / "0.8" / "index.html").write_text("0.8")
        plan_file = tmp_path / "plan.json"
        plan_file.write_text(plan_json)
        _main(
            [
                "assemble",
                "--dev",
                str(dev),
                "--snapshots",
                str(tmp_path / "snapshots"),
                "--plan",
                str(plan_file),
                "--out",
                str(tmp_path / "tree"),
            ]
        )
        assert (tmp_path / "tree" / "0.8" / "index.html").read_text() == "0.8"
