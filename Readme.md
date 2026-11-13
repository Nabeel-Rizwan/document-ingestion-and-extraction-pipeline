# Running and Testing the Document Pipeline

## 1. Prerequisites

| Tool | Version |
| ---- | ------- |
| Python | 3.12 (3.13/3.14 should also work) |
| Node.js | 18+ |
| Docker + Docker Compose | for the all-in-one stack |
| Postgres | 16 (only for local non-Docker backend) |

No external services, paid APIs, or network calls are used anywhere. OCR is
mocked behind an interface.


## 2. Quick start (Docker, everything in one command)

Start docker

```bash
cp .env.example .env
make up                 # or: docker compose up --build -d
```

Wait for all containers to be healthy:

```bash
docker compose ps
# db (healthy), backend, worker, frontend all Up
```

Open:

- Frontend UI: <http://localhost:8080>
- Django admin: <http://localhost:8000/admin/>

To stop:

```bash
make down               # or: docker compose down
```

To stop **and** delete data (database + uploaded media):

```bash
make clean              # or: docker compose down -v
```

# Running Tests

Run the tests now (no setup required)
make backend-test     # 114 passed, runs in Docker
make test             # backend + frontend
