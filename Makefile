SHELL := /bin/bash

.PHONY: up down logs test lint compile migrate graph

up:
	@test -f .env || cp .env.example .env
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f api

test:
	pytest -q

lint:
	ruff check services/api scripts

compile:
	python -m compileall -q services/api scripts

migrate:
	python scripts/migrate.py

graph:
	python scripts/rebuild_graph.py
