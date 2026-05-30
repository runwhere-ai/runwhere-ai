.PHONY: help install tailwind tailwind-watch dev test test-console test-webui test-e2e lint format clean

help:
	@echo "make install        Install Python deps (incl. gpuctl as path dep)"
	@echo "make tailwind       Build static/css/tailwind.css once"
	@echo "make tailwind-watch Watch & rebuild Tailwind on change"
	@echo "make dev            Run dev server with --reload"
	@echo "make test           Run all tests"
	@echo "make test-console   Unit tests for business library"
	@echo "make test-webui     Contract tests for UI routes"
	@echo "make test-e2e       Playwright E2E"
	@echo "make lint           Ruff lint"
	@echo "make format         Black format"
	@echo "make clean          Remove caches"

install:
	poetry install
	poetry run playwright install chromium
	./scripts/install-tailwind.sh

tailwind:
	./tools/tailwindcss -i static/css/runwhere.in.css -o static/css/tailwind.css --minify

tailwind-watch:
	./tools/tailwindcss -i static/css/runwhere.in.css -o static/css/tailwind.css --watch

dev: tailwind
	poetry run uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload

test:
	poetry run pytest

test-console:
	poetry run pytest tests/console -v

test-webui:
	poetry run pytest tests/webui -v

test-e2e:
	poetry run pytest tests/e2e -v

lint:
	poetry run ruff check src/ tests/

format:
	poetry run black src/ tests/

clean:
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov
	find . -type d -name __pycache__ -exec rm -rf {} +
