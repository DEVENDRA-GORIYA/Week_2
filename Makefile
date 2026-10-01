.PHONY: install test lint format run ui

install:
	cd backend && uv sync --all-groups

test:
	cd backend && uv run pytest

lint:
	cd backend && uv run ruff check . && uv run ruff format --check .

format:
	cd backend && uv run ruff format . && uv run ruff check --fix .

run:
	cd backend && uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

ui:
	python3 -m pip install -r ui/requirements.txt && cd ui && streamlit run app.py
