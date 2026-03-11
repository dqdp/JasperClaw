COMPOSE = docker compose -f infra/compose/compose.yml

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

format:
	ruff format services

lint:
	ruff check services

test:
	pytest services
