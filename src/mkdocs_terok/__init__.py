# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: 0BSD

"""Shared ProperDocs documentation generators for terok projects.

Provides reusable modules for CI maps, test maps, quality reports,
API reference pages, and Pydantic config reference rendering.
The ``terok`` ProperDocs plugin wraps all generators; individual modules
remain usable standalone (they never import properdocs themselves).
"""

from __future__ import annotations

from pathlib import Path

__version__ = "0.0.0"  # managed by poetry-dynamic-versioning


#: Env var honored by [`TerokPlugin.on_files`][mkdocs_terok.plugin.TerokPlugin.on_files]
#: to skip every generator that ``objects.inv`` doesn't depend on
#: (``ci_map``, ``quality_report``, ``test_map``, ``module_map``).
#: Set by [`mkdocs_terok.inventory.build_inventory`][] when subprocessing
#: ``properdocs build`` so a minimal ``poetry install --only main,docs``
#: env doesn't trip generators that need ``pytest``/``scc``/``vulture``.
#: Lives at the package root so both the plugin and the inventory builder
#: can read the same constant without crossing tach module boundaries.
INVENTORY_ONLY_ENV = "MKDOCS_TEROK_INVENTORY_ONLY"


def brand_css_path() -> Path:
    """Return the filesystem path to the shared brand CSS file."""
    return Path(__file__).parent / "_assets" / "extra.css"


def mermaid_zoom_js_path() -> Path:
    """Return the filesystem path to the Mermaid diagram zoom script."""
    return Path(__file__).parent / "_assets" / "mermaid_zoom.js"
