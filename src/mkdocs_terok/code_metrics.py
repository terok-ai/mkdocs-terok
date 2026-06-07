# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: 0BSD

"""Generate a code quality report as Markdown.

Runs complexipy, vulture, tach, scc, and docstr-coverage, then assembles
the results into a single Markdown page with a Mermaid dependency diagram.
Returns a [`CodeMetricsResult`][mkdocs_terok.code_metrics.CodeMetricsResult] containing the Markdown and any
companion files (e.g. SVGs) that the consumer should write alongside it.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html import escape as _xml_escape
from pathlib import Path

import squarify

_VENV_BIN = Path(sys.executable).parent


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CodeMetricsConfig:
    """Configuration for quality report generation.

    All paths are relative to ``root`` unless absolute. Sections gracefully
    degrade with warning admonitions when external tools are missing.
    """

    root: Path = field(default_factory=Path.cwd)
    src_dir: Path | None = None
    tests_dir: Path | None = None
    complexity_threshold: int = 15
    histogram_buckets: Sequence[tuple[int, int]] | None = None
    graph_depth: int = 3
    vulture_whitelist: Path | None = None
    vulture_min_confidence: int = 80
    coverage_json_path: Path | None = None
    treemap_group_depth: int = 3
    # codecov_repo is opt-in: when set *and* coverage_json_path is unavailable, the
    # report embeds Codecov's live treemap URL as a fallback. That image is fetched
    # by the visitor's browser, so it always reflects Codecov's *latest* master
    # coverage — it will not match the snapshot of the surrounding page if the page
    # was built from an older commit.
    codecov_repo: str = ""
    file_level_loc: bool = True
    include_layer_overview: bool = False
    include_graph_coarsening: bool = False
    src_label: str = "Source"
    tests_label: str = "Tests"

    def __post_init__(self) -> None:
        """Validate configuration values and normalize root to absolute."""
        object.__setattr__(self, "root", self.root.resolve())
        if self.graph_depth < 1:
            raise ValueError(f"graph_depth must be >= 1, got {self.graph_depth}")

    def _resolve(self, path: Path | None, default: str) -> Path:
        """Resolve a path relative to root, with a fallback default."""
        if path is None:
            return self.root / default
        return path if path.is_absolute() else self.root / path

    def _resolve_optional(self, path: Path | None) -> Path | None:
        """Resolve an optional path relative to root."""
        if path is None:
            return None
        return path if path.is_absolute() else self.root / path

    @property
    def resolved_src_dir(self) -> Path:
        """Return the source directory, falling back to ``src/`` under root."""
        return self._resolve(self.src_dir, "src")

    @property
    def resolved_tests_dir(self) -> Path:
        """Return the tests directory, falling back to ``tests/`` under root."""
        return self._resolve(self.tests_dir, "tests")

    @property
    def resolved_histogram_buckets(self) -> Sequence[tuple[int, int]]:
        """Return histogram buckets with default narrow bins if not configured."""
        if self.histogram_buckets is not None:
            return self.histogram_buckets
        return [
            (0, 3),
            (4, 6),
            (7, 9),
            (10, 12),
            (13, 15),
            (16, 18),
            (19, 21),
            (22, 25),
            (26, 999),
        ]


@dataclass
class CodeMetricsResult:
    """Result of quality report generation.

    Attributes:
        markdown: The full Markdown report content.
        companion_files: Mapping of relative paths to file contents that
            should be written alongside the report (e.g. SVGs).
    """

    markdown: str
    companion_files: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def generate_code_metrics(config: CodeMetricsConfig | None = None) -> CodeMetricsResult:
    """Assemble the full quality report.

    Args:
        config: Report configuration. Uses defaults if ``None``.

    Returns:
        A [`CodeMetricsResult`][mkdocs_terok.code_metrics.CodeMetricsResult] with the Markdown and companion files.
    """
    if config is None:
        config = CodeMetricsConfig()

    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    coverage_md, companion = _section_coverage_treemap(config)

    sections = [
        "# Code Metrics\n\n",
        f"*Generated: {now}*\n\n",
        "---\n\n",
        "## Lines of Code\n\n",
        _section_loc(config),
        "\n",
        "## Architecture\n\n",
    ]

    layer_overview = _section_layer_overview(config)
    if layer_overview:
        sections.append("### Layer Overview\n\n")
        sections.append(layer_overview)
        sections.append("\n")

    sections.extend(
        [
            "### Module Dependency Graph\n\n",
            _section_dependency_diagram(config),
            "\n",
            "### Module Boundaries\n\n",
            _section_boundary_check(config),
            "\n",
            "### Module Summary\n\n",
            _section_dependency_report(config),
            "\n",
            "## Test Coverage\n\n",
            coverage_md,
            "\n",
            "## Cognitive Complexity\n\n",
            f"Threshold: **{config.complexity_threshold}** (functions above this are listed below)\n\n",
            _section_complexity(config),
            "\n",
            "## Dead Code Analysis\n\n",
            _section_dead_code(config),
            "\n",
            "## Docstring Coverage\n\n",
            _section_docstring_coverage(config),
            "\n---\n\n",
            "*Generated by scc, complexipy, vulture, tach, and docstr-coverage.*\n",
        ]
    )

    return CodeMetricsResult(
        markdown="".join(sections),
        companion_files=companion,
    )


# ---------------------------------------------------------------------------
# Report sections (in assembly order)
# ---------------------------------------------------------------------------


def _section_coverage_treemap(cfg: CodeMetricsConfig) -> tuple[str, dict[str, str]]:
    """Generate the coverage treemap embed and return (markdown, companion_files).

    Priority:
        1. If ``coverage_json_path`` resolves to a Coverage.py JSON report, render
           a static SVG treemap locally and bundle it as a companion file.
        2. Else, if ``codecov_repo`` is set, embed Codecov's live ``tree.svg`` URL.
           This is fetched fresh by the visitor's browser, so it shows Codecov's
           latest master coverage — *not* the snapshot the surrounding page was
           built from.
        3. Else, emit an admonition explaining the section is unavailable.
    """
    companion: dict[str, str] = {}

    resolved_cov = cfg._resolve_optional(cfg.coverage_json_path)
    if resolved_cov and resolved_cov.is_file():
        try:
            data = json.loads(resolved_cov.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return (
                f"!!! warning\n    Coverage report `{resolved_cov}` could not be loaded: {exc}\n\n",
                companion,
            )
        svg = _render_coverage_treemap_svg(data, group_depth=cfg.treemap_group_depth)
        companion["coverage_treemap.svg"] = svg
        treemap = (
            '<object id="coverage-treemap-img" type="image/svg+xml" '
            'data="coverage_treemap.svg"></object>\n\n'
        )
        totals = data.get("totals", {})
        total_pct = totals.get("percent_covered")
        intro = (
            f"Overall line coverage: **{total_pct:.1f}%** "
            f"({totals.get('covered_lines', 0)}/{totals.get('num_statements', 0)} statements).\n\n"
            if isinstance(total_pct, (int, float))
            else ""
        )
        grouping = (
            "top-level subdirectory"
            if cfg.treemap_group_depth == 1
            else f"the first {cfg.treemap_group_depth} directory levels"
        )
        legend = (
            "Each rectangle is a source file. Area is proportional to the number of "
            "statements; colour encodes the coverage percentage (green = fully covered, "
            f"red = uncovered). Files are grouped by {grouping}.\n"
        )
        return intro + treemap + legend, companion

    if cfg.codecov_repo:
        base = f"https://codecov.io/gh/{cfg.codecov_repo}"
        live_src = f"{base}/graphs/tree.svg"
        treemap = (
            f'<object id="codecov-treemap-img" type="image/svg+xml" data="{live_src}"></object>\n\n'
        )
        md = (
            f"Coverage is uploaded to [Codecov]({base}). The treemap below is fetched "
            f"live from Codecov, so it always reflects the latest master coverage — "
            f"this may differ from the snapshot the rest of this page was built from.\n\n"
            "### Coverage Treemap\n\n"
            + treemap
            + "Each rectangle represents a source file. Size is proportional to the "
            "number of lines; colour shows the coverage percentage (green = high, "
            "red = low).\n"
        )
        return md, companion

    return (
        "!!! info\n    Coverage treemap not available "
        "(no `coverage.json` was produced for this build).\n\n",
        companion,
    )


# ---------------------------------------------------------------------------
# Local coverage treemap SVG generation
# ---------------------------------------------------------------------------


_TREEMAP_WIDTH = 1000
_TREEMAP_HEIGHT = 600
_GROUP_LABEL_HEIGHT = 14
_GROUP_PAD = 2


def _render_coverage_treemap_svg(coverage_data: dict, *, group_depth: int) -> str:
    """Render a coverage.py JSON report as an SVG treemap.

    Files are sized by ``summary.num_statements`` and coloured by
    ``summary.percent_covered``. Files are grouped into rectangles by the first
    ``group_depth`` segments of their path (capped to keep the file itself out
    of the group key).
    """
    items = [
        (path, summary.get("num_statements", 0), float(summary.get("percent_covered", 0.0)))
        for path, fdata in coverage_data.get("files", {}).items()
        if isinstance(summary := fdata.get("summary"), dict)
        and summary.get("num_statements", 0) > 0
    ]
    if not items:
        return _empty_treemap_svg("No coverage data")

    groups: dict[str, list[tuple[str, int, float]]] = defaultdict(list)
    for path, size, pct in items:
        parts = path.split("/")
        depth = max(1, min(group_depth, len(parts) - 1))
        groups["/".join(parts[:depth])].append((path, size, pct))

    group_totals = sorted(
        ((name, sum(s for _, s, _ in entries)) for name, entries in groups.items()),
        key=lambda gt: gt[1],
        reverse=True,
    )
    group_rects = squarify.squarify(
        squarify.normalize_sizes(
            [total for _, total in group_totals], _TREEMAP_WIDTH, _TREEMAP_HEIGHT
        ),
        0,
        0,
        _TREEMAP_WIDTH,
        _TREEMAP_HEIGHT,
    )

    svg: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_TREEMAP_WIDTH} '
        f'{_TREEMAP_HEIGHT}" font-family="-apple-system,BlinkMacSystemFont,sans-serif">',
        f'<rect width="{_TREEMAP_WIDTH}" height="{_TREEMAP_HEIGHT}" fill="#fafafa"/>',
    ]

    for (gname, _gtotal), grect in zip(group_totals, group_rects, strict=True):
        svg.extend(_render_group(gname, groups[gname], grect))

    svg.append("</svg>\n")
    return "\n".join(svg)


def _render_group(
    name: str, files: list[tuple[str, int, float]], rect: dict[str, float]
) -> list[str]:
    """Render one group rectangle and its child file rectangles."""
    gx, gy, gw, gh = rect["x"], rect["y"], rect["dx"], rect["dy"]
    label_h = _GROUP_LABEL_HEIGHT if gh > 30 else 0
    inner_x = gx + _GROUP_PAD
    inner_y = gy + label_h
    inner_w = max(1.0, gw - 2 * _GROUP_PAD)
    inner_h = max(1.0, gh - label_h - _GROUP_PAD)

    files_sorted = sorted(files, key=lambda f: f[1], reverse=True)
    file_rects = squarify.squarify(
        squarify.normalize_sizes([s for _, s, _ in files_sorted], inner_w, inner_h),
        inner_x,
        inner_y,
        inner_w,
        inner_h,
    )

    out: list[str] = [
        f'<g><rect x="{gx:.1f}" y="{gy:.1f}" width="{gw:.1f}" height="{gh:.1f}" '
        f'fill="#e8e8e8" stroke="#333" stroke-width="1.5"/>',
    ]
    if label_h:
        out.append(
            f'<text x="{gx + 4:.1f}" y="{gy + 11:.1f}" font-size="11" '
            f'fill="#222" font-weight="600">{_xml_escape(name)}</text>'
        )

    for (path, size, pct), frect in zip(files_sorted, file_rects, strict=True):
        out.append(_render_file_rect(path, size, pct, frect))

    out.append("</g>")
    return out


def _render_file_rect(path: str, size: int, pct: float, rect: dict[str, float]) -> str:
    """Render one file's rectangle with colour, tooltip, and optional label."""
    x, y, w, h = rect["x"], rect["y"], rect["dx"], rect["dy"]
    fname = path.rsplit("/", 1)[-1]
    tooltip = f"{path} — {pct:.1f}% ({size} stmts)"
    rect_svg = (
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
        f'fill="{_coverage_color(pct)}" stroke="#fff" stroke-width="0.5">'
        f"<title>{_xml_escape(tooltip)}</title></rect>"
    )
    if w > 40 and h > 12:
        label = _xml_escape(fname[: max(1, int(w / 6))])
        rect_svg += (
            f'<text x="{x + 2:.1f}" y="{y + 10:.1f}" font-size="9" '
            f'fill="#111" pointer-events="none">{label}</text>'
        )
    return rect_svg


def _coverage_color(pct: float) -> str:
    """Map coverage percentage to an HSL colour (red→yellow→green)."""
    pct = max(0.0, min(100.0, pct))
    hue = pct * 1.2  # 0 → red, 120 → green
    return f"hsl({hue:.0f},65%,55%)"


def _empty_treemap_svg(message: str) -> str:
    """Render a placeholder SVG when no coverage data is available."""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_TREEMAP_WIDTH} '
        f'{_TREEMAP_HEIGHT}"><rect width="{_TREEMAP_WIDTH}" height="{_TREEMAP_HEIGHT}" '
        f'fill="#fafafa"/><text x="{_TREEMAP_WIDTH // 2}" y="{_TREEMAP_HEIGHT // 2}" '
        f'text-anchor="middle" font-family="sans-serif" font-size="20" '
        f'fill="#666">{_xml_escape(message)}</text></svg>\n'
    )


def _section_loc(cfg: CodeMetricsConfig) -> str:
    """Generate lines-of-code statistics using scc."""
    import shutil

    if not shutil.which("scc"):
        return "!!! warning\n    `scc` not found — skipping LoC report. Install from https://github.com/boyter/scc\n"
    if not cfg.resolved_src_dir.is_dir():
        return "!!! warning\n    Source directory not found — skipping LoC report.\n"

    n = _nbsp_num
    src_totals = _scc_totals(cfg.resolved_src_dir, cwd=cfg.root)
    tests_totals = _scc_totals(cfg.resolved_tests_dir, cwd=cfg.root)

    comment_ratio = (
        f"{src_totals['comment'] / src_totals['code'] * 100:.0f}%" if src_totals["code"] else "—"
    )
    test_ratio = f"{tests_totals['code'] / src_totals['code']:.1%}" if src_totals["code"] else "—"

    combined_files = src_totals["files"] + tests_totals["files"]
    combined_code = src_totals["code"] + tests_totals["code"]
    combined_comment = src_totals["comment"] + tests_totals["comment"]
    combined_blank = src_totals["blank"] + tests_totals["blank"]
    combined_lines = src_totals["lines"] + tests_totals["lines"]

    lines = [
        "| | Files | Code | Comment | Blank | Total |\n",
        "|---|---:|---:|---:|---:|---:|\n",
        f"| {cfg.src_label} | {src_totals['files']} | {n(src_totals['code'])} | {n(src_totals['comment'])} | {n(src_totals['blank'])} | {n(src_totals['lines'])} |\n",
        f"| {cfg.tests_label} | {tests_totals['files']} | {n(tests_totals['code'])} | {n(tests_totals['comment'])} | {n(tests_totals['blank'])} | {n(tests_totals['lines'])} |\n",
        f"| **Combined** | **{combined_files}** | **{n(combined_code)}** | **{n(combined_comment)}** | **{n(combined_blank)}** | **{n(combined_lines)}** |\n",
        "\n",
        f"- **Comment/code ratio:** {comment_ratio}\n",
        f"- **Test/source ratio:** {test_ratio}\n",
        "\n",
    ]

    detail_lines: list[str] = []
    _walk_source_tree(
        cfg.resolved_src_dir,
        detail_lines,
        cwd=cfg.root,
        file_level=cfg.file_level_loc,
    )

    lines.append('??? info "Source by module (click to expand)"\n\n')
    lines.append("    | Module | Files | Code | Comment | Blank |\n")
    lines.append("    |---|---:|---:|---:|---:|\n")
    for dl in detail_lines:
        lines.append(f"    {dl}")
    lines.append("\n")

    return "".join(lines)


def _section_layer_overview(cfg: CodeMetricsConfig) -> str:
    """Generate a high-level layer dependency graph from tach.toml."""
    if not cfg.include_layer_overview:
        return ""
    loaded = _load_tach_toml(cfg.root)
    if not loaded:
        return ""
    _raw, _data, modules = loaded
    if not modules:
        return ""

    layer_of: dict[str, str] = {}
    layer_modules: dict[str, list[str]] = defaultdict(list)
    for m in modules:
        path = m.get("path", "")
        layer = m.get("layer", "?")
        layer_of[path] = layer
        short = path.split(".", 2)[-1] if path.count(".") >= 2 else path
        layer_modules[layer].append(short)

    layer_edges: dict[tuple[str, str], int] = defaultdict(int)
    for m in modules:
        src_layer = m.get("layer", "?")
        for dep_path in m.get("depends_on", []):
            dst_layer = layer_of.get(dep_path, "?")
            if src_layer != dst_layer:
                layer_edges[(src_layer, dst_layer)] += 1

    if not layer_edges and len(layer_modules) < 2:
        return ""

    lines = ["```mermaid\ngraph LR\n"]
    for layer in sorted(layer_modules):
        count = len(layer_modules[layer])
        lines.append(f'    {layer}["{layer} ({count} modules)"]\n')
    for (src, dst), count in sorted(layer_edges.items()):
        label = f"|{count} deps|" if count > 1 else ""
        lines.append(f"    {src} -->{label} {dst}\n")
    lines.append("```\n")
    return "".join(lines)


def _section_dependency_diagram(cfg: CodeMetricsConfig) -> str:
    """Generate module dependency diagram from tach."""
    result = _run(sys.executable, "-m", "tach", "show", "--mermaid", "-o", "-", cwd=cfg.root)
    if result.returncode != 0:
        output = (result.stdout + result.stderr).strip() or "no output"
        if "No dependency rules" in output:
            return "No cross-module dependencies to visualize.\n"
        return (
            f"!!! warning\n    tach show failed (exit {result.returncode}).\n\n```\n{output}\n```\n"
        )
    output = result.stdout.strip()
    if not output:
        return "!!! warning\n    tach show --mermaid produced no output.\n"

    if not cfg.include_graph_coarsening:
        return f"```mermaid\n{output}\n```\n"

    edge_lines = []
    in_graph = False
    for line in output.splitlines():
        if line.startswith("graph "):
            in_graph = True
            continue
        if in_graph:
            edge_lines.append(line)

    if not edge_lines:
        return "!!! warning\n    Could not parse mermaid output from tach.\n"

    coarsened = _coarsen_graph(edge_lines, cfg.graph_depth)
    return "```mermaid\n" + "\n".join(coarsened) + "\n```\n"


def _section_boundary_check(cfg: CodeMetricsConfig) -> str:
    """Run tach check and report results."""
    loaded = _load_tach_toml(cfg.root)
    mod_count = 0
    dep_count = 0
    if loaded:
        _raw, _data, modules = loaded
        mod_count = len(modules)
        dep_count = sum(len(m.get("depends_on", [])) for m in modules)

    result = _run(sys.executable, "-m", "tach", "check", cwd=cfg.root)
    output = (result.stdout + result.stderr).strip()
    if result.returncode == 0:
        stats = f"{mod_count} modules, {dep_count} dependency edges — " if mod_count else ""
        return f"{stats}all boundaries validated.\n"
    return f"```\n{output}\n```\n"


def _section_dependency_report(cfg: CodeMetricsConfig) -> str:
    """Generate a module dependency summary from tach.toml."""
    loaded = _load_tach_toml(cfg.root)
    if not loaded:
        return "!!! warning\n    `tach.toml` not found or unparseable — skipping module summary.\n"
    raw, _data, modules = loaded
    if not modules:
        return "No modules defined in `tach.toml`.\n"

    descriptions: list[str] = []
    raw_lines = raw.splitlines()
    for i, line in enumerate(raw_lines):
        if line.strip() == "[[modules]]":
            desc = (
                raw_lines[i - 1].lstrip("# ").strip()
                if i > 0 and raw_lines[i - 1].startswith("#")
                else ""
            )
            descriptions.append(desc)

    has_layers = any(m.get("layer") for m in modules)
    n_layers = len({m.get("layer", "?") for m in modules})

    if has_layers and cfg.include_layer_overview:
        header = f'??? info "{len(modules)} modules across {n_layers} layers (click to expand)"\n\n'
        col_header = "    | Module | Layer | Deps | Description |\n"
        col_separator = "    |---|---|---:|---|\n"
    else:
        header = f'??? info "{len(modules)} modules (click to expand)"\n\n'
        col_header = "    | Module | Deps | Description |\n"
        col_separator = "    |---|---:|---|\n"

    lines = [header, col_header, col_separator]
    for idx, mod in enumerate(modules):
        path = mod.get("path", "?")
        deps = len(mod.get("depends_on", []))
        raw_desc = descriptions[idx] if idx < len(descriptions) else ""
        desc = raw_desc.replace("|", r"\|").replace("\n", " ")
        if has_layers and cfg.include_layer_overview:
            layer = mod.get("layer", "?")
            lines.append(f"    | `{path}` | {layer} | {deps} | {desc} |\n")
        else:
            lines.append(f"    | `{path}` | {deps} | {desc} |\n")
    lines.append("\n")

    return "".join(lines)


def _section_complexity(cfg: CodeMetricsConfig) -> str:
    """Generate cognitive complexity section from complexipy."""
    run_result = _run(
        str(_VENV_BIN / "complexipy"),
        str(cfg.resolved_src_dir),
        "--ignore-complexity",
        cwd=cfg.root,
    )
    if run_result.returncode != 0:
        output = (run_result.stdout + run_result.stderr).strip()
        return f"!!! warning\n    complexipy failed; skipping complexity report.\n\n```\n{output}\n```\n"

    cache_dir = cfg.root / ".complexipy_cache"
    
    # Try new cache format first (complexipy >= 5.x): .complexipy_cache/v/cache/functions
    new_cache_file = cache_dir / "v" / "cache" / "functions"
    if new_cache_file.is_file():
        try:
            data = json.loads(new_cache_file.read_text(encoding="utf-8"))
            # New format: {"entries": {"hash": {"functions": [...]}}}
            functions: list[dict] = []
            for entry in data.get("entries", {}).values():
                if isinstance(entry, dict):
                    functions.extend(entry.get("functions", []))
        except (json.JSONDecodeError, OSError):
            return "!!! warning\n    complexipy cache is invalid JSON — skipping complexity report.\n"
    else:
        # Fall back to old cache format: .complexipy_cache/*.json
        cache_files = sorted(cache_dir.glob("*.json")) if cache_dir.is_dir() else []
        if not cache_files:
            return "!!! warning\n    complexipy cache not found — skipping complexity report.\n"

        latest_cache = max(cache_files, key=lambda p: p.stat().st_mtime)
        try:
            data = json.loads(latest_cache.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return "!!! warning\n    complexipy cache is invalid JSON — skipping complexity report.\n"

        # Old format: {"functions": [...]}
        functions = [
            f
            for f in data.get("functions", [])
            if isinstance(f, dict) and isinstance(f.get("complexity"), (int, float))
        ]
    if not functions:
        return "No functions found.\n"

    functions.sort(key=lambda f: f["complexity"], reverse=True)
    total = len(functions)
    scores = [int(f["complexity"]) for f in functions]
    over = [f for f in functions if f["complexity"] > cfg.complexity_threshold]
    max_c = scores[0] if scores else 0
    avg_c = sum(scores) / total if total else 0
    sorted_scores = sorted(scores)
    if total == 0:
        median_c: int | float = 0
    elif total % 2 == 1:
        median_c = sorted_scores[total // 2]
    else:
        median_c = (sorted_scores[total // 2 - 1] + sorted_scores[total // 2]) / 2
    pct = (total - len(over)) / total * 100 if total else 0

    lines = [
        f"- **Functions analyzed:** {total}\n",
        f"- **Median complexity:** {median_c} · **Average:** {avg_c:.1f} · **Max:** {max_c}\n",
        f"- **Within threshold ({cfg.complexity_threshold}):** {pct:.0f}%"
        f" ({total - len(over)}/{total})\n",
        "\n",
    ]

    buckets = cfg.resolved_histogram_buckets
    bar_max = 30
    bucket_counts = [(lo, hi, sum(1 for s in scores if lo <= s <= hi)) for lo, hi in buckets]
    peak = max(c for _, _, c in bucket_counts) if bucket_counts else 1

    lines.append("```\n")
    for lo, hi, count in bucket_counts:
        if count == 0 and lo > max(scores, default=0):
            continue
        label = f"{lo:>3d}–{hi:>3d}" if hi < 999 else f"{lo:>3d}+   "
        bar_len = round(count / peak * bar_max) if peak else 0
        bar = "█" * bar_len
        pct_bin = count / total * 100 if total else 0
        marker = " ◄ threshold" if lo <= cfg.complexity_threshold <= hi else ""
        lines.append(f"  {label} │ {bar:<{bar_max}} {count:>3d} ({pct_bin:4.1f}%){marker}\n")
    lines.append("```\n\n")

    if over:
        lines.append(f"**{len(over)} functions exceeding threshold:**\n\n")
        lines.append("| Complexity | Function | File |\n|---:|---|---|\n")
        for f in over:
            lines.append(
                f"| {f['complexity']} | `{f.get('function_name', '<unknown>')}` | `{f.get('path', '<unknown>')}` |\n"
            )
    else:
        lines.append(
            f"All functions are within the cognitive complexity threshold of"
            f" {cfg.complexity_threshold}.\n"
        )

    return "".join(lines)


def _section_dead_code(cfg: CodeMetricsConfig) -> str:
    """Generate dead code section from vulture."""
    cmd = [sys.executable, "-m", "vulture", str(cfg.resolved_src_dir)]
    resolved_whitelist = cfg._resolve_optional(cfg.vulture_whitelist)
    if resolved_whitelist is not None:
        cmd.append(str(resolved_whitelist))
    cmd.extend(["--min-confidence", str(cfg.vulture_min_confidence)])

    result = _run(*cmd, cwd=cfg.root)
    output = (result.stdout + result.stderr).strip()
    if not output:
        if result.returncode != 0:
            return f"!!! warning\n    vulture failed (exit {result.returncode}).\n"
        return f"No dead code found at {cfg.vulture_min_confidence}% confidence threshold.\n"

    def _md_cell(value: str) -> str:
        """Escape pipe and newline characters for Markdown table cells."""
        return value.replace("|", r"\|").replace("\n", " ")

    lines = ["| Confidence | Location | Issue |\n", "|---:|---|---|\n"]
    parsed = 0
    for line in output.splitlines():
        if "% confidence)" in line:
            parts = line.rsplit("(", 1)
            location_msg = parts[0].strip()
            confidence = parts[1].rstrip(")").strip()
            loc_parts = location_msg.split(": ", 1)
            location = loc_parts[0] if loc_parts else location_msg
            message = loc_parts[1] if len(loc_parts) > 1 else ""
            lines.append(
                f"| {_md_cell(confidence)} | `{_md_cell(location)}` | {_md_cell(message)} |\n"
            )
            parsed += 1
        else:
            lines.append(f"| — | — | {_md_cell(line)} |\n")
    if parsed == 0 and result.returncode != 0:
        return f"!!! warning\n    vulture failed.\n\n```text\n{output}\n```\n"
    return "".join(lines)


def _section_docstring_coverage(cfg: CodeMetricsConfig) -> str:
    """Generate docstring coverage section."""
    result = _run(
        str(_VENV_BIN / "docstr-coverage"),
        str(cfg.resolved_src_dir),
        "--fail-under=0",
        cwd=cfg.root,
    )
    output = (result.stdout + result.stderr).strip()
    summary = []
    for line in output.splitlines():
        if any(kw in line for kw in ("Needed:", "Total coverage:", "Grade:")):
            summary.append(f"- {line.strip()}\n")
    if not summary:
        return f"```\n{output}\n```\n"
    return "".join(summary)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _run(*cmd: str, cwd: Path, timeout_seconds: float = 120.0) -> subprocess.CompletedProcess[str]:
    """Run a command and return the result (never raises on failure)."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="timed out")
    except FileNotFoundError as exc:
        return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr=str(exc))


def _nbsp_num(n: int) -> str:
    """Format an integer with non-breaking spaces as thousand separators."""
    return f"{n:,}".replace(",", "\u00a0")


_EMPTY_TOTALS: dict[str, int] = {"lines": 0, "code": 0, "comment": 0, "blank": 0, "files": 0}


def _scc_totals(path: Path, *, cwd: Path) -> dict[str, int]:
    """Run scc on *path* and return aggregated totals across all languages."""
    result = _run("scc", "--format", "json", "--no-cocomo", str(path), cwd=cwd)
    if result.returncode != 0 or not result.stdout.strip():
        return dict(_EMPTY_TOTALS)
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return dict(_EMPTY_TOTALS)
    totals = dict(_EMPTY_TOTALS)
    for lang in data:
        if lang.get("Name", "") in ("Total", "SUM"):
            continue
        totals["lines"] += lang.get("Lines", 0)
        totals["code"] += lang.get("Code", 0)
        totals["comment"] += lang.get("Comment", 0)
        totals["blank"] += lang.get("Blank", 0)
        totals["files"] += lang.get("Count", 0)
    return totals


def _scc_file_totals(path: Path, *, cwd: Path) -> dict[str, int]:
    """Run scc on a single file and return its totals."""
    result = _run("scc", "--format", "json", "--no-cocomo", str(path), cwd=cwd)
    if result.returncode != 0 or not result.stdout.strip():
        return dict(_EMPTY_TOTALS)
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return dict(_EMPTY_TOTALS)
    for lang in data:
        if lang.get("Name", "") in ("Total", "SUM"):
            continue
        return {
            "lines": lang.get("Lines", 0),
            "code": lang.get("Code", 0),
            "comment": lang.get("Comment", 0),
            "blank": lang.get("Blank", 0),
            "files": 1,
        }
    return dict(_EMPTY_TOTALS)


def _walk_source_tree(
    base: Path, lines: list[str], *, cwd: Path, file_level: bool, prefix: str = ""
) -> None:
    """Recursively collect LoC table rows for files and subdirs under *base*."""
    if not base.is_dir():
        return
    n = _nbsp_num
    entries = sorted(base.iterdir(), key=lambda p: (p.is_file(), p.name))
    for entry in entries:
        if entry.name == "__pycache__":
            continue
        if entry.is_dir():
            t = _scc_totals(entry, cwd=cwd)
            if t["code"] == 0 and t["lines"] == 0:
                continue
            label = f"{prefix}{entry.name}/"
            lines.append(
                f"| `{label}` | {t['files']} | {n(t['code'])} | {n(t['comment'])} | {n(t['blank'])} |\n"
            )
            _walk_source_tree(entry, lines, cwd=cwd, file_level=file_level, prefix=label)
        elif file_level and entry.suffix == ".py":
            t = _scc_file_totals(entry, cwd=cwd)
            if t["code"] == 0:
                continue
            lines.append(
                f"| `{prefix}{entry.name}` | — | {n(t['code'])} | {n(t['comment'])} | {n(t['blank'])} |\n"
            )


def _load_tach_toml(root: Path) -> tuple[str, dict, list[dict]] | None:
    """Load and parse tach.toml, returning (raw_text, parsed_data, modules) or None."""
    tach_path = root / "tach.toml"
    if not tach_path.is_file():
        return None
    raw = tach_path.read_text(encoding="utf-8")
    try:
        data = tomllib.loads(raw)
    except tomllib.TOMLDecodeError:
        return None
    modules = data.get("modules", [])
    return (raw, data, modules)


def _coarsen_module(name: str, depth: int) -> str:
    """Truncate a dotted module path to *depth* segments."""
    return ".".join(name.split(".")[:depth])


def _coarsen_graph(mermaid_lines: list[str], depth: int) -> list[str]:
    """Aggregate fine-grained mermaid edges into a coarser high-level graph.

    Edges between sub-modules of the same group are dropped. Duplicate
    coarsened edges are collapsed and annotated with a count.
    """
    edge_re = re.compile(r"^\s*(.+?)\s*-->\s*(.+?)\s*$")
    edge_counts: dict[tuple[str, str], int] = defaultdict(int)
    nodes: set[str] = set()

    for line in mermaid_lines:
        m = edge_re.match(line)
        if not m:
            continue
        src = _coarsen_module(m.group(1).strip(), depth)
        dst = _coarsen_module(m.group(2).strip(), depth)
        nodes.add(src)
        nodes.add(dst)
        if src != dst:
            edge_counts[(src, dst)] += 1

    out = ["graph TD"]
    for (src, dst), count in sorted(edge_counts.items()):
        label = f"|{count}|" if count > 1 else ""
        out.append(f"    {src} -->{label} {dst}")
    connected = {n for pair in edge_counts for n in pair}
    for node in sorted(nodes - connected):
        out.append(f"    {node}")
    return out
