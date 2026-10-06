.PHONY: up down build logs test backend-test backend-test-local frontend-test frontend-test-local lint backend-lint frontend-lint clean

up:
	docker compose up --build -d

down:
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f

# Backend suite runs inside the project image (source bind-mounted, Postgres
# auto-started). No host Python packages required.
backend-test:
	docker compose run --rm \
		-v "$(CURDIR)/backend:/app" \
		-e PYTHONDONTWRITEBYTECODE=1 \
		backend python -m pytest tests -p no:cacheprovider

# Frontend typecheck + unit tests via the image's `test` stage. No host Node.
frontend-test:
	docker build --target test ./frontend

test: backend-test frontend-test

# Host fallbacks (only if you have your own venv / Node install).
backend-test-local:
	cd backend && python -m pytest tests

frontend-test-local:
	cd frontend && npm test

backend-lint:
	docker compose run --rm backend python -m compileall -q pipeline documents config

frontend-lint:
	docker build --target test ./frontend

lint: backend-lint frontend-lint

clean:
	docker compose down -v
