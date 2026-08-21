.PHONY: bootstrap up down logs migrate admin test lint build clean

bootstrap:
	@test -f .env || cp .env.example .env
	docker compose build

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

migrate:
	docker compose exec backend alembic upgrade head

admin:
	docker compose exec backend python -m app.cli bootstrap-admin

test:
	docker compose run --rm backend pytest
	docker compose run --rm web npm test -- --run

lint:
	docker compose run --rm backend ruff check .
	docker compose run --rm backend mypy app
	docker compose run --rm web npm run lint

build:
	docker compose build

clean:
	docker compose down --remove-orphans
