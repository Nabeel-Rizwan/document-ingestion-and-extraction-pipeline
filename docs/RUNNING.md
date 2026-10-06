# Running and Testing the Document Pipeline

Everything you need to get the stack running locally and to run the full test
suite. Commands assume you are in the repository root unless stated otherwise.

---

## 1. Prerequisites

| Tool | Version |
| ---- | ------- |
| Python | 3.12 (3.13/3.14 should also work) |
| Node.js | 18+ |
| Docker + Docker Compose | for the all-in-one stack |
| Postgres | 16 (only for local non-Docker backend) |
| Tesseract OCR | real OCR (only for local non-Docker backend; bundled in the Docker image) |

At runtime no external services, paid APIs, or network calls are used. Real OCR
runs locally through Tesseract (installed in the Docker image); set
`OCR_ENGINE=mock` to use the canned mock instead.

---

## 2. Quick start (Docker, everything in one command)

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
- Backend API: <http://localhost:8000/api/>
- Django admin: <http://localhost:8000/admin/> (also available through the
  frontend at <http://localhost:8080/admin/>)

To stop:

```bash
make down               # or: docker compose down
```

To stop **and** delete data (database + uploaded media):

```bash
make clean              # or: docker compose down -v
```

---

## 3. Local development without Docker

### 3.1 Backend

1. Start a Postgres 16 database and create the `documents` user/db. With the
   default env this is:

   ```sql
   CREATE USER documents WITH PASSWORD 'documents';
   CREATE DATABASE documents OWNER documents;
   ```

2. Install Tesseract for real OCR (skip if you only need text-layer PDFs or
   will use `OCR_ENGINE=mock`):

   ```bash
   # macOS
   brew install tesseract
   # Debian/Ubuntu
   sudo apt-get install -y tesseract-ocr
   ```

3. Set up the Python environment and install dependencies:

   ```bash
   cd backend
   python3.12 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

4. Configure env (optional — defaults work for a local Postgres). `OCR_ENGINE`
   defaults to `tesseract`; set it to `mock` to avoid needing the binary:

   ```bash
   export POSTGRES_DB=documents
   export POSTGRES_USER=documents
   export POSTGRES_PASSWORD=documents
   export POSTGRES_HOST=localhost
   export POSTGRES_PORT=5432
   export OCR_ENGINE=tesseract   # or: mock
   ```

5. Create the schema. **Do not hand-edit migration files** — generate them:

   ```bash
   python manage.py makemigrations documents
   python manage.py migrate
   ```

6. Run the two processes (two terminals):

   ```bash
   # Terminal 1 — the job worker
   python manage.py run_worker

   # Terminal 2 — the API server
   uvicorn config.asgi:application --host 0.0.0.0 --port 8000
   ```

The API is now at <http://localhost:8000/api/>.

### 3.2 Frontend

```bash
cd frontend
npm install
npm run dev
```

Vite serves the SPA at <http://localhost:5173> and proxies `/api` to
`http://localhost:8000` (change the target with `VITE_API_PROXY_TARGET`).

---

## 4. Running the tests

### 4.1 Backend — pipeline core only (no database needed)

```bash
cd backend
python -m pytest tests/pipeline
```

This is pure Python and never touches a database. Expect **55 passed**. The
Tesseract wrapper test (`tests/pipeline/test_ocr.py`) stubs `pytesseract`, so
Tesseract is not required to run this subset.

### 4.2 Backend — full suite (needs Postgres)

The full suite runs the pipeline tests **and** the Django/API tests
(uploads, worker, queue concurrency, SSE, search, agent tools). These need a
running Postgres 16 with the credentials above.

```bash
cd backend
source .venv/bin/activate     # if not already
python -m pytest tests
```

Expect **109 passed**. The API tests force `OCR_ENGINE=mock`, so they are
deterministic and do not require a Tesseract install.

Notes:
- If you see `database "test_documents" already exists` from a previously
  interrupted run, force a clean test database with:
  ```bash
  python -m pytest tests --create-db
  ```
- The queue-concurrency and SSE tests use real threads/transactions by
  design, so the test database is dropped between runs.

### 4.3 Frontend

```bash
cd frontend
npm run typecheck    # TypeScript strict
npm test             # Vitest + React Testing Library (24 tests)
npm run build        # production build
```

All three must pass.

### 4.4 Everything via Makefile

```bash
make test             # backend full suite + frontend tests
make lint             # backend compile + frontend typecheck
```

---

## 5. Manual end-to-end smoke test

After the stack is up (Docker **or** local), walk the whole pipeline by hand.

**1. Check the API and accepted formats:**

```bash
curl -s http://localhost:8000/api/config/
# {"max_upload_bytes":26214400,"supported":[{"kind":"pdf",...},{"kind":"docx",...}]}
```

**2. Create a test PDF and upload it:**

```bash
cd backend && source .venv/bin/activate
python -c "
from tests.factories import make_digital_pdf
from pathlib import Path
print(make_digital_pdf(pages=2, tmp_path=Path('/tmp')))
"

curl -s -X POST http://localhost:8000/api/documents/ -F "file=@/tmp/digital_2p.pdf"
```

Save the returned `id`. Uploading the same file again returns the same id
with `"duplicate": true`.

**3. Watch it process (SSE):**

```bash
curl -s -N http://localhost:8000/api/documents/<ID>/events/
# event: progress  →  event: done
```

Or just wait a few seconds, then:

```bash
curl -s http://localhost:8000/api/documents/
```

The document should now be `status: "done"`, `stage: "done"`,
`method: "pdf_text"`, `progress: 1.0`.

**4. Read the extracted content (five formats):**

```bash
curl -s "http://localhost:8000/api/documents/<ID>/content/?format=json"
curl -s "http://localhost:8000/api/documents/<ID>/content/?format=markdown"
curl -s "http://localhost:8000/api/documents/<ID>/content/?format=text&page=1"
curl -s "http://localhost:8000/api/documents/<ID>/content/?format=html"
curl -s "http://localhost:8000/api/documents/<ID>/content/?format=csv"
# download as an attachment (sets Content-Disposition: attachment)
curl -sOJ "http://localhost:8000/api/documents/<ID>/content/?format=markdown&download=1"
```

To exercise OCR, build a scanned or short-text PDF instead:

```bash
python -c "
from tests.factories import make_scanned_pdf, make_short_text_pdf
from pathlib import Path
print(make_short_text_pdf('Hello world', tmp_path=Path('/tmp')))   # text layer
print(make_scanned_pdf(pages=1, tmp_path=Path('/tmp')))            # image → OCR
"
```

A digital page reports `method: pdf_text`; a page with an embedded image and no
text layer reports `method: pdf_ocr` (or `pdf_mixed`). OCR confidence is stored
in each OCR block's `metadata.confidence`.

**5. Download the original:**

```bash
curl -s -OJ "http://localhost:8000/api/documents/<ID>/download/"
```

**6. Search (note the ⟦ ⟧ headline markers):**

```bash
curl -s "http://localhost:8000/api/search/?q=digital"
```

**7. Agent tool interface:**

```bash
curl -s http://localhost:8000/api/agent/tools/

curl -s -X POST http://localhost:8000/api/agent/tools/call/ \
  -H 'Content-Type: application/json' \
  -d '{"name": "search_documents", "arguments": {"query": "page"}}'
```

**8. In the browser** — upload a PDF or DOCX via the dropzone and watch the
live progress bar; once done, open the document to see the **Preview / HTML /
Markdown / Plain text / CSV / JSON** tabs (each with copy and download), the
document details panel, and, for PDFs, the per-page Text/OCR sidebar.

---

## 6. Error-code cheat sheet

| HTTP | `error.code` | Meaning |
| ---- | ------------ | ------- |
| 400 | `bad_request` | missing `file`, empty file, bad `page`, bad query |
| 404 | `not_found` | unknown document id |
| 409 | `not_ready` | content requested before `status=done` |
| 413 | `too_large` | file exceeds `MAX_UPLOAD_BYTES` |
| 415 | `unsupported_type` | sniffed kind has no registered extractor |

Document failure states use `error_code`: `corrupt`, `encrypted`,
`unsupported`, `empty` (permanent, never retried) or `internal` (transient
error retried up to `WORKER_MAX_ATTEMPTS` then failed).

---

## 7. Common issues

- **Port 5432 already in use** — stop any other local Postgres before
  `docker compose up`, or change the db port mapping.
- **`database "test_documents" already exists`** — add `--create-db` to the
  pytest command.
- **Upload returns 500 `PermissionError: /media`** — the Docker backend runs
  as a non-root user; rebuild the image after pulling the current
  `backend/Dockerfile` (`docker compose build backend worker`).
- **Frontend can't reach the API** — with `npm run dev` ensure the backend is
  on `:8000`, or set `VITE_API_PROXY_TARGET`.

---

## 8. How to add a new format (quick reminder)

Create one extractor class, register it in
`backend/pipeline/registry.py::default_registry`, and nothing else changes —
`GET /api/config/` advertises the new extension, upload validation accepts it,
and the dropzone picks it up automatically. A worked `TxtExtractor` example is
in the README.