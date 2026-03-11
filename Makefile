COMPOSE = docker compose -f infra/compose/compose.yml
PYTHON ?= python3
VENV ?= .venv
VENV_PYTHON = $(VENV)/bin/python
VENV_PIP = $(VENV_PYTHON) -m pip
RUFF = $(VENV)/bin/ruff

$(VENV_PYTHON):
	$(PYTHON) -m venv $(VENV)
	$(VENV_PIP) install --upgrade pip
	$(VENV_PIP) install -r requirements-dev.txt

venv: $(VENV_PYTHON)

sync: $(VENV_PYTHON)
	$(VENV_PIP) install --upgrade pip
	$(VENV_PIP) install -r requirements-dev.txt

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=200

ps:
	$(COMPOSE) ps

smoke:
	bash infra/scripts/smoke.sh

format: $(VENV_PYTHON)
	$(RUFF) format services

lint: $(VENV_PYTHON)
	$(RUFF) check services

test: $(VENV_PYTHON)
	PYTHON_BIN=$(VENV_PYTHON) bash infra/scripts/test-python-services.sh
