.PHONY: up down build test backend-test frontend-test lint clean

up:
	docker compose up --build -d

down:
	docker compose down

build:
	docker compose build

backend-test:
	cd backend && pytest tests

frontend-test:
	cd frontend && npm test

test: backend-test frontend-test

backend-lint:
	cd backend && python -m compileall -q pipeline documents config

frontend-lint:
	cd frontend && npm run typecheck

lint: backend-lint frontend-lint

clean:
	docker compose down -v