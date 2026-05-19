.PHONY: help install dev lint test ping clean check-python

# Auto-detect the newest Python 3.11+ available. Override with `make PYTHON=python3.12 dev` if needed.
PYTHON ?= $(shell for v in python3.13 python3.12 python3.11 python3; do \
    command -v $$v >/dev/null 2>&1 && \
    $$v -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' 2>/dev/null && \
    echo $$v && break; \
done)

check-python:
	@if [ -z "$(PYTHON)" ]; then \
        echo ""; \
        echo "ERROR: No Python 3.11 or newer was found on your PATH."; \
        echo ""; \
        echo "  Install one of these:"; \
        echo "    brew install python@3.12     # macOS, Homebrew"; \
        echo "    pyenv install 3.12.4         # pyenv users"; \
        echo ""; \
        echo "  Then re-run 'make dev'."; \
        echo ""; \
        exit 1; \
    fi
	@echo "Using $(PYTHON) ($$($(PYTHON) --version))"

help:
	@echo "make install   — create .venv and install in editable mode"
	@echo "make dev       — same as install plus dev dependencies (pytest, ruff)"
	@echo "make lint      — run ruff"
	@echo "make test      — run pytest"
	@echo "make ping      — run 'doc-agent ping' (requires .env with API key)"
	@echo "make clean     — remove caches and build artifacts"

install: check-python
	$(PYTHON) -m venv .venv
	. .venv/bin/activate && pip install --upgrade pip && pip install -e .

dev: check-python
	$(PYTHON) -m venv .venv
	. .venv/bin/activate && pip install --upgrade pip && pip install -e ".[dev]"

lint:
	. .venv/bin/activate && ruff check src tests

test:
	. .venv/bin/activate && pytest

ping:
	. .venv/bin/activate && doc-agent ping

clean:
	rm -rf .venv build dist *.egg-info .pytest_cache .ruff_cache .mypy_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
