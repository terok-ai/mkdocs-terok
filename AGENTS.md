# Agent Guide (mkdocs-terok)

## Purpose

`mkdocs-terok` provides shared ProperDocs documentation generators for terok projects.
It produces strings/results that consumers wrap in thin mkdocs-gen-files shims.

The package name stays `mkdocs-terok` for install-path stability; internally the
plugin imports from `properdocs.*`. ProperDocs' plugin loader reads both
`mkdocs.plugins` and `properdocs.plugins` entry-point groups, so the
`[tool.poetry.plugins."mkdocs.plugins"]` declaration is preserved intentionally.

## Technology Stack

- **Language**: Python 3.12+
- **Package Manager**: Poetry
- **Testing**: pytest with coverage
- **Linting/Formatting**: ruff
- **Documentation**: N/A (library is self-documenting via docstrings)

## Build, Lint, and Test Commands

```bash
make lint       # Run linter (required before every commit)
make format     # Auto-fix lint issues if lint fails
make test       # Run full test suite with coverage
make docstrings # Check docstring coverage (minimum 95%)
make deadcode   # Find dead code
make reuse      # Check REUSE (SPDX license/copyright) compliance
make check      # Run lint + test + docstrings + deadcode + reuse
```

## Coding Standards

- **Style**: Follow ruff configuration in `pyproject.toml`
- **Line length**: 100 characters
- **Type hints**: Use Python 3.12+ type hints
- **Docstrings**: Required for all public functions, classes, and modules (95% min)
- **Cross-references in docstrings**: use mkdocstrings autoref syntax `` [`Name`][module.path.Name] `` — never the Sphinx ``:class:`Name``` / ``:func:`name``` forms. Sphinx roles render as literal text on the rendered docs site (mkdocstrings doesn't process them). Prefer the explicit full path over the bare `` [`Name`][] `` autoref form: explicit paths keep `properdocs build --strict` green even when the symbol's short name isn't unique. For external symbols, use the dependency's own path (e.g. `` [`Sandbox`][terok_sandbox.Sandbox] ``, `` [`StreamReader`][asyncio.StreamReader] ``) — those resolve via the inventories listed in `properdocs.yml`.
- **SPDX headers**: Every `.py` file must have an SPDX header
- **No runtime dependency on the doc engine in generator modules**: Only
  `plugin.py` imports `properdocs`; each generator module produces strings and
  consumers handle I/O

## Dependency Pinning & `pyproject.toml` Hygiene

**Version pinning policy.** Runtime/production dependencies — those pulled in
by a plain `pip install` / `pipx install` of this package (the
`[project].dependencies` table) — are pinned by the dependency's major
version:

- **Third-party, major 0 (`0.y.z`)** → pin to an **exact patch**
  (`pkg==0.y.z`). Pre-1.0 packages promise no compatibility across either
  minors *or* patches, so a floating range invites silent breakage.
- **Third-party, major ≥ 1** → pin by **range** (e.g. `pkg>=2.6`), trusting
  the package to honour semver. If a specific `>=1` dependency is known to
  break semver, tighten it deliberately.
- **Sibling `terok-*` deps** → **exempt**: keep ranges (or their
  release-wheel URL pin). We guarantee patch-level API stability across the
  sibling packages, so a `0.y` range there will not silently break — do
  *not* exact-pin them (it would fight the multi-repo release/PR-chain flow).

Dev / test / docs / tooling dependencies (the `[tool.poetry.group.*]` groups)
are **exempt** — they are not shipped to installers and exact-pinning them is
an unwarranted maintenance burden the developers can absorb. After changing
any pin, run `poetry lock` and commit `pyproject.toml` and `poetry.lock`
together.

**No comments in `pyproject.toml`.** Do **not** add comments to
`pyproject.toml`, with the single exception of the standing dependency-pinning
policy note above the `dependencies` table. In particular **never** add a
comment about a dependency that is temporarily pinned to a git branch during a
multi-repo PR chain, and never mention the PR-chain workflow in
`pyproject.toml` at all. Cross-repo merges are performed by a script that does
not understand comments, so any stray dev-cycle comment is carried straight
into a production release. Keep such rationale in commit messages, PR
descriptions, or this file.
