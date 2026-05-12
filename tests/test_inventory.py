# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: 0BSD

"""Tests for the sibling-decoupled inventory builder."""

from __future__ import annotations

import subprocess
import textwrap
from collections.abc import Callable
from pathlib import Path

import pytest

from mkdocs_terok import INVENTORY_ONLY_ENV
from mkdocs_terok.inventory import (
    _main,
    _strip_sibling_inventory_lines,
    build_inventory,
)


class TestStripSiblingInventoryLines:
    """Verify the textual stripper drops only sibling-terok inventory list items."""

    def test_strips_legacy_pages_urls(self) -> None:
        """``terok-ai.github.io/<repo>/objects.inv`` lines disappear."""
        text = textwrap.dedent("""\
            inventories:
              - https://docs.python.org/3/objects.inv
              - https://terok-ai.github.io/terok/objects.inv
              - https://terok-ai.github.io/terok-sandbox/objects.inv
              - https://terok-ai.github.io/mkdocs-terok/objects.inv
        """)
        out = _strip_sibling_inventory_lines(text)
        assert "docs.python.org" in out
        assert "terok-ai.github.io" not in out

    def test_strips_new_bucket_urls(self) -> None:
        """``raw.githubusercontent.com/terok-ai/docs-inventories/...`` lines disappear."""
        text = textwrap.dedent("""\
            inventories:
              - https://raw.githubusercontent.com/terok-ai/docs-inventories/main/terok/objects.inv
              - https://docs.pydantic.dev/latest/objects.inv
        """)
        out = _strip_sibling_inventory_lines(text)
        assert "docs-inventories" not in out
        assert "pydantic" in out

    def test_preserves_non_sibling_urls(self) -> None:
        """Stdlib + third-party inventories survive the strip."""
        text = textwrap.dedent("""\
            inventories:
              - https://docs.python.org/3/objects.inv
              - https://docs.pydantic.dev/latest/objects.inv
              - https://example.com/things/objects.inv
        """)
        assert _strip_sibling_inventory_lines(text) == text

    def test_does_not_match_dependency_pin_urls(self) -> None:
        """Wheel pins under ``terok-ai.github.io/.../releases/...`` are not list items.

        ``pyproject.toml`` references like
        ``url = "https://github.com/.../wheel.whl"`` never start with the YAML
        ``- `` list marker, so the line filter must leave them untouched even
        when they contain ``terok-ai`` substrings.
        """
        text = textwrap.dedent("""\
            terok-sandbox = {url = "https://github.com/terok-ai/terok-sandbox/releases/download/v0.0.115/terok_sandbox-0.0.115-py3-none-any.whl"}
            terok-executor = {url = "https://github.com/terok-ai/terok-executor/releases/download/v0.0.140/terok_executor-0.0.140-py3-none-any.whl"}
        """)
        assert _strip_sibling_inventory_lines(text) == text

    def test_preserves_trailing_newline(self) -> None:
        """A trailing newline survives the round-trip (mkdocs is fussy)."""
        text = "key: value\n"
        assert _strip_sibling_inventory_lines(text).endswith("\n")

    def test_handles_no_trailing_newline(self) -> None:
        """No trailing newline in → none out (don't manufacture whitespace)."""
        text = "key: value"
        assert not _strip_sibling_inventory_lines(text).endswith("\n")

    def test_strips_with_indentation_variants(self) -> None:
        """Various leading-whitespace amounts are all matched."""
        text = textwrap.dedent("""\
            handlers:
              python:
                inventories:
                            - https://terok-ai.github.io/terok-shield/objects.inv
                  - https://terok-ai.github.io/terok-clearance/objects.inv
            -    https://terok-ai.github.io/terok-executor/objects.inv
        """)
        out = _strip_sibling_inventory_lines(text)
        assert "terok-ai.github.io" not in out


class _FakeProperdocs:
    """Minimal ``subprocess.run`` double standing in for ``properdocs build``.

    Captures the patched ``--config-file`` text the orchestrator wrote (so
    tests can assert on the strip), and lets each scenario decide whether
    to write ``site/objects.inv`` and what return code to fake.
    """

    def __init__(
        self,
        *,
        write_inventory: bool = True,
        inventory_bytes: bytes = b"OBJECTS_INV_DATA",
        on_run: Callable[[list[str]], None] | None = None,
    ) -> None:
        self.write_inventory = write_inventory
        self.inventory_bytes = inventory_bytes
        self.on_run = on_run
        self.captured_config_text: str | None = None
        self.last_cmd: list[str] | None = None
        self.last_env: dict[str, str] | None = None

    def __call__(self, cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        self.last_cmd = cmd
        env = kwargs.get("env")
        self.last_env = env if isinstance(env, dict) else None
        cfg_path = Path(cmd[cmd.index("--config-file") + 1])
        self.captured_config_text = cfg_path.read_text()
        site_dir = Path(cmd[cmd.index("--site-dir") + 1])
        site_dir.mkdir(parents=True, exist_ok=True)
        if self.write_inventory:
            (site_dir / "objects.inv").write_bytes(self.inventory_bytes)
        if self.on_run is not None:
            self.on_run(cmd)
        return subprocess.CompletedProcess(cmd, 0)


def _make_config(tmp_path: Path, body: str = "site_name: x\n") -> Path:
    """Write *body* to ``tmp_path/properdocs.yml`` and return the path."""
    cfg = tmp_path / "properdocs.yml"
    cfg.write_text(body)
    return cfg


class TestBuildInventory:
    """Verify the orchestration around the ``properdocs build`` subprocess."""

    def test_happy_path_copies_inventory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Successful build copies ``site/objects.inv`` to the requested output."""
        cfg = _make_config(tmp_path)
        out = tmp_path / "out" / "objects.inv"
        fake = _FakeProperdocs()
        monkeypatch.setattr(subprocess, "run", fake)

        build_inventory(config=cfg, output=out)

        assert out.read_bytes() == b"OBJECTS_INV_DATA"
        # Patched config is cleaned up regardless of success.
        assert not list(tmp_path.glob(".inventory-*.yml"))

    def test_strips_sibling_urls_from_patched_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The config handed to ``properdocs build`` has sibling URLs removed."""
        cfg = _make_config(
            tmp_path,
            body=textwrap.dedent("""\
                inventories:
                  - https://terok-ai.github.io/terok-sandbox/objects.inv
                  - https://docs.python.org/3/objects.inv
            """),
        )
        fake = _FakeProperdocs()
        monkeypatch.setattr(subprocess, "run", fake)

        build_inventory(config=cfg, output=tmp_path / "objects.inv")

        assert fake.captured_config_text is not None
        assert "terok-ai.github.io" not in fake.captured_config_text
        assert "docs.python.org" in fake.captured_config_text

    def test_subprocess_failure_propagates_and_cleans_up(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``CalledProcessError`` propagates; the patched config is still removed."""
        cfg = _make_config(tmp_path)

        def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess:
            raise subprocess.CalledProcessError(7, cmd)

        monkeypatch.setattr(subprocess, "run", fake_run)
        with pytest.raises(subprocess.CalledProcessError) as exc:
            build_inventory(config=cfg, output=tmp_path / "objects.inv")

        assert exc.value.returncode == 7
        assert not list(tmp_path.glob(".inventory-*.yml"))

    def test_missing_objects_inv_raises_file_not_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A successful build that doesn't emit ``objects.inv`` raises clearly."""
        cfg = _make_config(tmp_path)
        monkeypatch.setattr(subprocess, "run", _FakeProperdocs(write_inventory=False))

        with pytest.raises(FileNotFoundError, match="objects.inv was not produced"):
            build_inventory(config=cfg, output=tmp_path / "objects.inv")

    def test_creates_output_parent_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Nested output paths get their parents created on the fly."""
        cfg = _make_config(tmp_path)
        out = tmp_path / "deep" / "nested" / "objects.inv"
        monkeypatch.setattr(subprocess, "run", _FakeProperdocs())

        build_inventory(config=cfg, output=out)

        assert out.is_file()

    def test_subprocess_env_sets_inventory_only_flag(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``properdocs build`` is invoked with ``MKDOCS_TEROK_INVENTORY_ONLY=1``.

        That env var is the contract that lets the ``terok`` plugin skip
        generators which would fail in a stripped-down install (test_map
        without pytest, quality_report without scc/vulture, …).  Without
        it set, the inventory build trips on the first such generator.
        """
        cfg = _make_config(tmp_path)
        fake = _FakeProperdocs()
        monkeypatch.setattr(subprocess, "run", fake)
        # Strip the env var from the parent process if a prior test left
        # it set; the assertion below is meaningful only when the value
        # comes from build_inventory itself.
        monkeypatch.delenv(INVENTORY_ONLY_ENV, raising=False)

        build_inventory(config=cfg, output=tmp_path / "objects.inv")

        assert fake.last_env is not None
        assert fake.last_env.get(INVENTORY_ONLY_ENV) == "1"


class TestMain:
    """Verify the ``python -m mkdocs_terok.inventory`` exit-code translation."""

    def test_success_exits_cleanly(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A clean run returns from ``_main`` without raising ``SystemExit``."""
        cfg = _make_config(tmp_path)
        out = tmp_path / "objects.inv"
        monkeypatch.setattr(subprocess, "run", _FakeProperdocs())

        _main(["-c", str(cfg), "-o", str(out)])

        assert out.is_file()

    def test_subprocess_failure_exits_with_returncode(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CalledProcessError → ``sys.exit(returncode)`` so CI sees the original code."""
        cfg = _make_config(tmp_path)

        def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess:
            raise subprocess.CalledProcessError(42, cmd)

        monkeypatch.setattr(subprocess, "run", fake_run)
        with pytest.raises(SystemExit) as exc:
            _main(["-c", str(cfg), "-o", str(tmp_path / "objects.inv")])

        assert exc.value.code == 42

    def test_missing_inventory_exits_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """FileNotFoundError → ``sys.exit(1)`` and the message goes to stderr."""
        cfg = _make_config(tmp_path)
        monkeypatch.setattr(subprocess, "run", _FakeProperdocs(write_inventory=False))

        with pytest.raises(SystemExit) as exc:
            _main(["-c", str(cfg), "-o", str(tmp_path / "objects.inv")])

        assert exc.value.code == 1
        assert "objects.inv was not produced" in capsys.readouterr().err
