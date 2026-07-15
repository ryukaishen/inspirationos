# Wraps the canonical commands for CI and the VPS. On the Windows dev box
# (no make), run the underlying commands directly — see TESTING_STRATEGY.md.
# A `fixture` target arrives with M2's backend/tests/fixture_builder.py.

.PHONY: dev test migrate e2e

dev:
	docker compose up --build

test:
	cd backend && python -m ruff format --check . && python -m ruff check . && python -m mypy app && python -m pytest -q
	cd frontend && npm run lint && npx tsc --noEmit && npm run test -- --run

migrate:
	cd backend && python -m alembic upgrade head

e2e:
	docker compose up -d --build
	cd e2e && npx playwright test
