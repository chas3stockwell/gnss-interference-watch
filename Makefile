# Local checks. SAM uses the Makefile inside each function directory, not this one.
.PHONY: test lint format

test:
	pytest

lint:
	ruff check .
	ruff format --check .

format:
	ruff format .
	ruff check --fix .
