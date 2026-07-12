.PHONY: all lint format test test-fast docstrings deadcode reuse readme-version check install install-dev clean spdx docs docs-serve

REPORTS_DIR ?= reports
COVERAGE_XML ?= $(REPORTS_DIR)/coverage.xml
JUNIT_XML ?= $(REPORTS_DIR)/tests.junit.xml

all: check

# Run linter and format checker (fast, run before commits)
lint:
	@if LC_ALL=C grep -nP '[^\x00-\x7F]' pyproject.toml; then echo "pyproject.toml must be ASCII-only"; exit 1; fi
	mkdir -p $(REPORTS_DIR)
	uv run ruff check .
	uv run ruff format --check .

# Auto-fix lint issues and format code
format:
	uv run ruff check --fix .
	uv run ruff format .

# Fast dev loop: run only the tests affected by the branch diff (tach
# impact analysis), no coverage.  Impact analysis follows the Python
# import graph only — after touching non-Python inputs (YAML, templates,
# scripts) run the full `make test` instead.
test-fast:
	uv run pytest tests/ --tach

# Run tests with coverage
test:
	mkdir -p $(REPORTS_DIR)
	uv run pytest tests/ --cov --cov-report=term-missing --cov-report=xml --junitxml=$(JUNIT_XML) -o junit_family=legacy

# Check docstring coverage (minimum 95%)
docstrings:
	uv run docstr-coverage src/mkdocs_terok/ --fail-under=95

# Find dead code (cross-file, min 80% confidence)
deadcode:
	uv run vulture src/mkdocs_terok/ --min-confidence 80

# Check REUSE (SPDX license/copyright) compliance
reuse:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	uv run reuse lint

# Check README's install snippet pins the right major.minor for this version
readme-version:
	python3 scripts/check-readme-version.py

# Run all checks (equivalent to CI)
check: lint test docstrings deadcode reuse readme-version

# Install runtime dependencies only
install:
	uv sync --no-default-groups

# Install all dependencies (dev, test, docs)
install-dev:
	uv sync --all-groups

# Clean build artifacts
clean:
	rm -rf dist/ reports/ site/ .coverage .pytest_cache/ .ruff_cache/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# Build documentation site
docs:
	uv run properdocs build --strict

# Serve documentation locally with live reload
docs-serve:
	uv run properdocs serve

# Add SPDX header to files.
spdx:
ifndef NAME
	$(error NAME is required — use the real name of the copyright holder, e.g. make spdx NAME="Real Human Name" FILES="src/mkdocs_terok/new_file.py")
endif
	uv run reuse annotate --template compact --copyright "$(NAME)" --license 0BSD $(FILES)
