# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: 0BSD

"""Tests for package-level exports and asset path helpers."""

from mkdocs_terok import brand_css_path, mermaid_zoom_js_path


def test_brand_css_path_exists() -> None:
    """brand_css_path() points to an existing CSS file."""
    path = brand_css_path()
    assert path.exists()
    assert path.suffix == ".css"


def test_mermaid_zoom_js_path_exists() -> None:
    """mermaid_zoom_js_path() points to an existing JS file."""
    path = mermaid_zoom_js_path()
    assert path.exists()
    assert path.suffix == ".js"


def test_mermaid_zoom_js_has_spdx_header() -> None:
    """The shipped JS asset contains a valid SPDX header."""
    text = mermaid_zoom_js_path().read_text(encoding="utf-8")
    assert "SPDX-License-Identifier" in text
    assert "SPDX-FileCopyrightText" in text


def test_version_falls_back_without_package_metadata(monkeypatch) -> None:
    """No installed metadata -> the placeholder version survives the import."""
    import importlib
    import importlib.metadata

    import mkdocs_terok

    def _missing(_name: str) -> str:
        raise importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(importlib.metadata, "version", _missing)
    try:
        assert importlib.reload(mkdocs_terok).__version__ == "0.0.0"
    finally:
        monkeypatch.undo()
        importlib.reload(mkdocs_terok)
