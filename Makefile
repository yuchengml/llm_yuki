.PHONY: install lint format typecheck test test-cov clean

install:
	poetry install

lint:
	poetry run ruff check .

format:
	poetry run ruff format .

typecheck:
	poetry run mypy src

test:
	poetry run pytest

test-cov:
	poetry run pytest --cov=src --cov-report=term-missing --cov-report=html

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov coverage.xml dist build
