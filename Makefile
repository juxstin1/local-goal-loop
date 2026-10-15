.PHONY: format lint test

format:
	uv run ruff format src tests scripts

lint:
	uv run ruff check src tests scripts

test:
	uv run pytest
