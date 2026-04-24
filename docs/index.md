# mkdocs-terok

Shared [ProperDocs](https://properdocs.org/) documentation generators for terok projects.

## Overview

`mkdocs-terok` ships a **`terok` ProperDocs plugin** that drives all built-in
generators automatically — no shim scripts required. For advanced or
consumer-specific use cases the generator modules remain public and can be
called directly via [`mkdocs-gen-files`](https://github.com/oprypin/mkdocs-gen-files).

## Quick start — plugin

```yaml
# properdocs.yml
plugins:
  - search
  - terok:
      ci_map: true
      quality_report: true
      test_map: true
      ref_pages: true
```

All generators default to **false** (opt-in). CSS and JS assets are injected
automatically unless `inject_css` / `inject_js` are set to `false`.

## Quick start — generator API

Each module produces Markdown strings or structured results that consumers wrap
in thin `mkdocs-gen-files` callbacks:

```python
from mkdocs_terok.ci_map import generate_ci_map

markdown = generate_ci_map()
```

The generators have **no runtime dependency on the doc engine** — they handle
content generation only.

## Modules

| Module | Purpose |
|--------|---------|
| `mkdocs_terok` | Package root — exports `brand_css_path()` and `mermaid_zoom_js_path()` |
| `mkdocs_terok.plugin` | ProperDocs `BasePlugin` wrapping all generators |
| `mkdocs_terok.ref_pages` | Generate API reference pages from source tree |
| `mkdocs_terok.ci_map` | Parse and visualize GitHub Actions workflows |
| `mkdocs_terok.quality_report` | Code quality analysis — optionally parses output from [scc](https://github.com/boyter/scc), [complexipy](https://github.com/rohaquinern/complexipy), [tach](https://github.com/gauge-sh/tach), [vulture](https://github.com/jendrikseipp/vulture), and [docstr-coverage](https://github.com/HunterMcGushion/docstr_coverage) (sections degrade gracefully when tools are absent) |
| `mkdocs_terok.test_map` | Generate test suite maps with marker extraction |
| `mkdocs_terok.config_reference` | Render Pydantic models as config documentation |

## Dogfooding

This documentation site **uses mkdocs-terok on itself**. Every generator in the
library is exercised against this very repository via the `terok` plugin.

The [Config Reference Demo](config-reference.md) uses a Star Trek-themed Pydantic
model to exercise all three renderers (`render_model_tables`, `render_yaml_example`,
`render_json_schema`) — it remains as a `mkdocs-gen-files` script since it requires
a consumer-specific Pydantic model.
