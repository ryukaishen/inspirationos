# Wraps the canonical commands for CI and the VPS. On the Windows dev box
# (no make), run the underlying commands directly — see TESTING_STRATEGY.md.
# A `fixture` target arrives with M2's backend/tests/fixture_builder.py.

.PHONY: dev test migrate e2e deploy-build deploy-migrate deploy-up backup restore

dev:
	docker compose up --build

test:
	cd backend && python -m ruff format --check . && python -m ruff check . && python -m mypy app && python -m pytest -q
	cd frontend && npm run lint && npx tsc --noEmit && npm run test -- --run

migrate:
	cd backend && python -m alembic upgrade head

e2e:
	docker compose up -d --build
	docker compose exec -T backend python -m app.cli create-user \
		--email e2e@example.com --password e2e-test-password-not-a-secret
	cd e2e && npx playwright test

# --- production (M9; see DEPLOYMENT_PLAN.md) --------------------------------
# docker-compose.prod.yml is standalone (not merged with docker-compose.yml)
# — every target below points at it explicitly, never with -f docker-compose.yml.

deploy-build:
	docker compose -f docker-compose.prod.yml build

# Migrations are an explicit step, never run automatically on container
# start — rehearse this against a copy of prod data before a real deploy.
deploy-migrate:
	docker compose -f docker-compose.prod.yml run --rm backend alembic upgrade head

deploy-up:
	docker compose -f docker-compose.prod.yml up -d

backup:
	bash backend/scripts/backup.sh

restore:
	bash backend/scripts/restore.sh $(DB_BACKUP) $(DATA_BACKUP)
