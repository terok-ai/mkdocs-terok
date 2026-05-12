# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: 0BSD

"""Tests for the sibling-decoupled inventory builder."""

from __future__ import annotations

import textwrap

from mkdocs_terok.inventory import _strip_sibling_inventory_lines


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
