PYTHON ?= python
COMPOSE ?= docker compose
.PHONY: install up down migrate demo live smoke test integration openapi production logs
install:
	$(PYTHON) -m pip install -r requirements-dev.lock
	$(PYTHON) -m pip install --no-deps -e .
up:
	$(COMPOSE) up -d --build --wait
down:
	$(COMPOSE) down
migrate:
	$(COMPOSE) run --rm migrate
demo:
	$(COMPOSE) exec api python scripts/demo.py
live:
	$(PYTHON) scripts/live_validation.py --sources gleif ted eurlex ocds
smoke:
	$(COMPOSE) exec api python scripts/smoke.py
test:
	$(PYTHON) -m pytest -q services/api/tests
integration:
	TRACE_INTEGRATION=1 $(PYTHON) -m pytest -q tests/integration
openapi:
	$(PYTHON) scripts/export_openapi.py
production:
	$(COMPOSE) --env-file .env.production -f compose.production.yml up -d --build --wait
logs:
	$(COMPOSE) logs --tail=100 api postgres
