.PHONY: bootstrap up down logs migrate admin test lint build clean

bootstrap:
	@test -f .env || cp .env.example .env
	docker compose build
	docker compose run --rm migrate

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

migrate:
	docker compose run --rm migrate

admin:
	docker compose run --rm api python -m app.cli bootstrap-admin

test:
	docker compose run --rm api pytest
	docker compose run --rm web npm test -- --run

lint:
	docker compose run --rm api ruff check .
	docker compose run --rm api mypy app
	docker compose run --rm web npm run lint

build:
	docker compose build

clean:
	docker compose down --remove-orphans
