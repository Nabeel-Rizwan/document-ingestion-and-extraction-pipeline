# Architecture

This document explains the overall system architecture, the technology choices,
and how Docker is used and configured for the document-ingestion pipeline.

---

## 1. What the system does

Users upload `.pdf` and `.docx` files through a browser. The backend:

1. Sniffs the file's *real* type (magic bytes, never the extension).
2. Routes it to the right extractor — PDF pages are further split into
   digital-text vs scanned (OCR) pages per page.
3. Extracts content into a normalised **block** structure.
4. Persists blocks in Postgres with full-text search.
5. Exposes the results through a REST API, a Server-Sent Events (SSE) stream
   for live progress, and an OpenAI-style agent-tool interface.

The UI renders extracted content in **five formats** (JSON / Markdown / plain
text / HTML / CSV, per page) with copy and download, streams live processing
progress, and lets users search with highlighted hits.

---

## 2. System architecture

### 2.1 Component diagram

```
Browser (React SPA)
   │  /api/*  (REST + SSE)
   ▼
nginx ── serves the built SPA, proxies /api + /admin + /static
   │        (proxy buffering off so SSE streams live)
   ▼
Django ASGI (uvicorn) ────────► Postgres 16 ◄─────── Worker (manage.py run_worker)
   │  DRF views + async SSE view      ▲                       │
   │                                 │                        ▼
   └──► media volume (raw files) ◄────┴─────── pipeline/ (pure Python)
                                                  router → extractor → blocks
```

There are four runtime pieces:

| Piece | What it runs | Why it exists |
| ----- | ------------ | ------------- |
| `db` | Postgres 16 | Single source of truth: documents, blocks, job queue, progress events |
| `backend` | uvicorn serving Django ASGI | Handles uploads, REST, SSE, admin; runs migrations on start |
| `worker` | `python manage.py run_worker` | Claims jobs from the queue and runs the extraction pipeline |
| `frontend` | nginx serving the built SPA | Static hosting plus reverse proxy to the backend |

### 2.2 Runtime view

- **API** (`backend`) and **worker** (`worker`) are separate processes over the
  *same* codebase, both talking to Postgres. The API never extracts; the
  worker never serves HTTP.
- **Storage**: raw uploads live on a shared `media` volume mounted into both
  the backend (write) and worker (read).
- **Progress**: the worker writes denormalised `Document.status/stage/progress`
  columns plus `ProgressEvent` rows. The API's SSE view reads those rows and
  streams them to the browser, so no broker or in-memory fan-out is needed.

### 2.3 Request lifecycle (end to end)

1. **Upload** — the browser streams each file to `POST /api/documents/` (max 3
   concurrent) via `XMLHttpRequest` so the upload panel can show a real
   per-file **byte-progress bar**; on acceptance the row switches to the
   document's live **processing progress**. The view hashes (SHA-256) and
   enforces `MAX_UPLOAD_BYTES` while writing a temp file. It sniffs the type
   with `pipeline/probe.py`. Duplicate content (same hash) returns the existing
   document; otherwise a `Document` row **and** a queued `Job` are created in
   one transaction (202 Accepted).
2. **Queue** — the worker claims jobs with
   `SELECT … FOR UPDATE SKIP LOCKED` (`documents/queue.py`), so concurrent
   workers never grab the same job. Stale `running` jobs (lock older than
   `WORKER_STALE_AFTER_SECONDS`) are re-queued for crash recovery.
3. **Pipeline** — `documents/processing.py::process_job` runs the pure-Python
   `pipeline.service.run_pipeline` against a local filesystem path. Progress is
   reported through a `DbProgressReporter` that updates the document columns
   and appends `ProgressEvent` rows.
4. **Indexing** — inside one transaction the old blocks are deleted, new blocks
   are `bulk_create`d, and the Postgres `search` vector column is populated.
   The document is marked `done`, `progress: 1.0`, and a final `done` SSE
   event is emitted.
5. **Live progress** — the UI opens an `EventSource` on
   `GET /api/documents/{id}/events/`. Each event patches the React Query caches.
   On stream failure the UI falls back to polling `GET /api/documents/{id}/`
   every 1.5 s until the document is terminal.
6. **Retrieval** — content is served as `json` / `markdown` / `text` / `html` /
   `csv` (optionally per page, or as a `download=1` attachment). Search uses
   Postgres full-text search (`websearch`) with
   `⟦ ⟧`-wrapped headline matches that the frontend renders as `<mark>` — it
   never injects HTML.

### 2.4 Error model

Permanent failures (`corrupt`, `encrypted`, `unsupported`, `empty`) are
`ExtractionError` subclasses that fail the document immediately. Any other
exception is treated as transient and retried up to `WORKER_MAX_ATTEMPTS`
before the document fails with `internal`. Every API failure is a uniform
envelope: `{"error": {"code", "message"}}`.

---

## 3. Tech stack and why

### 3.1 Frontend

| Choice | Reason |
| ------ | ------ |
| **React 18 + TypeScript (strict)** | Strong typing for the document/block shapes; the `SseEvent` and API types mirror the backend contract 1:1 |
| **Vite 5** | Fast dev server, proxy of `/api` to the backend in dev, and the production build tool |
| **React Router 6** | Library (`/`) and document detail (`/documents/:id`) views |
| **TanStack React Query 5** | Cache-first data fetching; the SSE hook *patches* query caches on each event so the UI updates live without refetches |
| **Upload queue** | Up to 3 concurrent `XMLHttpRequest` uploads with per-file **byte progress**; an accepted file's row then shows the document's live **processing progress** |
| **Content viewer** | Tabs for **Preview / HTML / Markdown / Plain text / CSV / JSON**, each with copy and `download=1` export; HTML is previewed in a sandboxed iframe. Short documents render all blocks, long ones page in via "Show more" |
| **Vitest + React Testing Library** | Unit/component tests in `jsdom` (24 tests) |

### 3.2 Backend

| Choice | Reason |
| ------ | ------ |
| **Python 3.12** | The extraction pipeline is pure Python and stays testable without a database |
| **Django 5.2 + Django REST Framework** | Mature ORM, admin panel, migrations, and DRF for the REST API |
| **uvicorn (ASGI)** | One server serves both the sync DRF views and the *async* SSE view (Django's async ORM support) |
| **Postgres 16** | `SELECT … FOR UPDATE SKIP LOCKED` for a safe multi-worker queue, and full-text search (`SearchVector` / `SearchHeadline`) with a GIN index |
| **psycopg 3** | Async-capable Postgres driver for the async SSE view |
| **pypdf / pypdfium2 / python-docx** | PDF text layer, PDF→image rendering for OCR, and DOCX body parsing |
| **Tesseract via pytesseract** | Real local OCR (bundled in the Docker image); selected by `OCR_ENGINE`, swappable for a cloud engine behind `OcrClient` |

### 3.3 Extraction pipeline

The pipeline is a deliberately decoupled, protocol-driven layer
(`backend/pipeline/`), pure Python with **no Django imports**:

- **`probe.py`** — sniffs magic bytes (`%PDF-`, DOCX = ZIP containing
  `word/document.xml`). Extensions are never trusted; mismatches become
  warnings.
- **`registry.py`** — the single source of truth for supported formats. Upload
  validation *and* the frontend's accepted-file list both derive from it via
  `GET /api/config/`, so adding a format is one new extractor.
- **`router.py`** — two-layer routing: pick an extractor by sniffed kind, then
  the extractor's `plan()` makes finer decisions (per-page text vs OCR).
- **`extractors/`** — `PdfExtractor` (pypdf for text, pypdfium2 for page
  rendering into OCR input, per-page classifier in `pdf_classifier.py`) and
  `DocxExtractor` (python-docx, walking the body in document order so
  paragraphs and tables stay interleaved). The classifier routes a page to OCR
  only when it has no text layer, garbled text, or sparse text **over an
  embedded image** — so short real text pages are trusted.
- **`ocr/`** — OCR is behind an `OcrClient` protocol. The default
  `TesseractOcrClient` runs real OCR via `pytesseract` (confidence = mean
  Tesseract word confidence), selected by `OCR_ENGINE`; `MockOcrClient` returns
  canned text and is used by the tests. Swapping in Textract/Azure requires
  **zero pipeline changes**.
- **`progress.py`** — progress is a protocol (`ProgressReporter`) with fixed
  stage bands (`detecting` 0–0.10, `extracting` 0.10–0.85, `indexing`
  0.85–1.0). Django provides a DB-backed reporter; tests use recording/null
  reporters, keeping the pipeline runnable with no database.
- **`schema.py`** — frozen dataclasses (`Block`, `ExtractionPlan`,
  `ExtractionResult`) that flow through the pipeline.
- **`renderers.py`** — pure functions that turn blocks into the output formats
  the API exposes: `render_markdown`, `render_text`, `render_html` (escaped,
  grouped lists/tables, page breaks) and `render_csv` (one row per block).
  HTML/CSV/Markdown all escape or quote user text so nothing is injected.

### 3.4 Why these choices in combination

- **Postgres as the job queue** (a table, not a broker) keeps the deployable
  surface small — no Redis/Celery/RabbitMQ — while still being concurrency-safe
  and crash-recoverable. It is a deliberate trade-off for this scale, not a
  permanent one (a dedicated queue is the documented next step).
- **Denormalised status on `Document`** makes list reads cheap and gives the
  SSE view a single source of truth.
- **Shared retrieval code** (`documents/services.py`) backs both the REST API
  and the agent tools, so the two interfaces can never drift.

---

## 4. How Docker is used and configured

### 4.1 Compose orchestration (`docker-compose.yml`)

One `docker compose up` starts the whole stack. The project name is
`document-pipeline`.

- **`db`** — `postgres:16` with a healthcheck (`pg_isready`) so `backend` and
  `worker` start only once the database is actually ready (`depends_on:
  condition: service_healthy`). Data is persisted in the `pgdata` named volume.
- **`backend`** — builds `backend/Dockerfile`, runs `entrypoint.sh` as its
  command, and exposes port `8000`. It depends on `db` being healthy.
- **`worker`** — same image as the backend, but a different command
  (`python manage.py run_worker`). This is the "one image, two roles" pattern.
- **`frontend`** — builds `frontend/Dockerfile`, exposes port `8080`, and
  proxies to the backend container by its compose service name (`backend`).

Environment is injected with `env_file: .env.example` plus a few compose-level
overrides (`POSTGRES_HOST: db`, `MEDIA_ROOT: /media`) — the only way a
container knows about *other* containers is `db` and `backend` from compose
networking.

### 4.2 Backend image (`backend/Dockerfile`)

- Based on `python:3.12-slim`.
- `PYTHONDONTWRITEBYTECODE` / `PYTHONUNBUFFERED` / `PIP_NO_CACHE_DIR` keep the
  image lean and logs live.
- Installs the Tesseract OCR binaries (`apt-get install tesseract-ocr
  tesseract-ocr-eng`) so real OCR works out of the box.
- Creates a non-root user `app` (uid/gid 1000) and pre-creates
  `/media` + `/app/staticfiles`, owned by it. The container runs as `USER app`
  — the "PermissionError: /media" gotcha in `docs/RUNNING.md` happens when an
  image predating this is run.
- Dependencies are installed before source is copied (`COPY requirements.txt`
  then `RUN pip install`, then `COPY --chown=app:app . .`) so dependency layers
  are cached across rebuilds.
- Default `CMD` is `uvicorn config.asgi:application` — used by the worker only
  as a fallback, since compose overrides the command.

### 4.3 Backend entrypoint (`backend/entrypoint.sh`)

The backend container's real command. It runs `set -e`, then:

1. `python manage.py collectstatic --noinput` — uvicorn does not serve static
   files, so admin CSS/JS are gathered into `staticfiles/`.
2. `python manage.py migrate --noinput` — schema is applied on every start,
   so there is no separate migrate step.
3. `exec uvicorn …` — `exec` replaces the shell so signals and stdin go
   straight to uvicorn (important for `docker stop`).

The worker image shares `Dockerfile` but not the entrypoint — its compose
`command` is `python manage.py run_worker`.

### 4.4 Frontend image (`frontend/Dockerfile`)

A **multi-stage build**:

1. **Build stage** (`node:20-alpine`): `npm ci` (or `npm install` if the
   lockfile is missing), then `npm run build` (TypeScript `tsc -b` + `vite
   build`). Produces `dist/`.
2. **Serve stage** (`nginx:1.27-alpine`): copies only the built `dist/` and
   `nginx.conf`. The final image contains no Node toolchain, no source, no
   `node_modules` — just static files + nginx.

### 4.5 nginx (`frontend/nginx.conf`)

nginx serves three kinds of traffic:

- `/` — SPA with history-API fallback (`try_files … /index.html`).
- `/api/` — proxied to `http://backend:8000` with **buffering off**, cache
  off, `X-Accel-Buffering: no`, and long read/send timeouts (300 s) so the
  **SSE stream flows to the browser as it is produced** instead of being
  buffered until the connection closes.
- `/admin/` and `/static/` — proxied to the backend so the Django admin is
  reachable from the same origin as the SPA.

The upstream is referenced through a variable (`set $backend "http://backend:8000"`)
with Docker's embedded DNS resolver (`resolver 127.0.0.11 valid=10s`). This
makes nginx re-resolve the backend's IP, so recreating the backend container
(which gets a new IP) causes at most a few seconds of 502 and then self-heals —
without the stale-address 502 you get from a literal `proxy_pass http://backend:8000`.

### 4.6 Shared volumes

- `pgdata` — Postgres data (survives restarts, gone with `docker compose down -v`).
- `media` — raw uploaded files, mounted into both `backend` (writes on upload)
  and `worker` (reads during extraction). Both containers also override
  `MEDIA_ROOT` to `/media` so they agree on the path.

### 4.7 Environment / secrets handling

- All configuration is **env-driven** with safe local defaults
  (`backend/config/settings.py` reads `os.environ.get(..., default)`).
- Compose loads `.env.example` via `env_file`. `.env` is gitignored; nothing
  secret is baked into images or committed.
- `ALLOWED_HOSTS` includes the compose service name `backend` (host header the
  proxy sends) plus localhost entries.
- Pipeline tuning is env-driven too: `MAX_UPLOAD_BYTES`, `OCR_ENGINE`
  (`tesseract`/`mock`), `OCR_LANGUAGES`, `OCR_MOCK_LATENCY`,
  `WORKER_MAX_ATTEMPTS`, `WORKER_STALE_AFTER_SECONDS`, `WORKER_POLL_INTERVAL`.

### 4.8 Makefile

`Makefile` wraps the common workflows:

| Target | Runs |
| ------ | ---- |
| `make up` / `down` / `build` | `docker compose up --build -d` / `down` / `build` |
| `make test` | backend pytest suite + frontend tests |
| `make lint` | backend `compileall` + frontend `tsc --noEmit` |
| `make clean` | `docker compose down -v` (delete data + uploads) |

---

## 5. Ports and URLs

| URL | Service |
| --- | ------- |
| `http://localhost:8080` | Frontend SPA (nginx) |
| `http://localhost:8080/api/` | API through the proxy |
| `http://localhost:8080/admin/` | Django admin through the proxy |
| `http://localhost:8000/api/` | Backend API directly |
| `http://localhost:8000/admin/` | Django admin directly |
| `http://localhost:5432` | Postgres (host mapping) |

---

## 6. Testing

The suite is split so that most of the logic is testable **without a database**
and the integration paths are tested against a **real Postgres** (never a
mocked ORM). Current totals: **109 backend tests** (55 pure-Python + 54
Django/API) and **24 frontend tests**.

### 6.1 How to run the tests

```bash
# Backend — pure-Python pipeline only (no database needed)
cd backend && python -m pytest tests/pipeline        # 55 tests

# Backend — full suite (needs Postgres 16 running)
cd backend && python -m pytest tests                 # 109 tests

# If a previous run left a stale test DB behind:
cd backend && python -m pytest tests --create-db

# Frontend — typecheck, unit tests, production build
cd frontend && npm run typecheck && npm test && npm run build

# Everything through the Makefile
make test     # backend full suite + frontend tests
make lint     # backend compileall + frontend tsc --noEmit
```

`backend/pytest.ini` points pytest at `config.settings`, sets
`python_files = test_*.py`, and turns warnings into **errors**
(`filterwarnings = error`), so tests fail on stray deprecations rather than
silently hiding them.

### 6.2 Test fixtures and factories

No binary documents are committed. `backend/tests/factories.py` builds them
programmatically with reportlab/pypdf/python-docx/Pillow:

| Factory | Produces | Used to test |
| ------- | -------- | ------------ |
| `make_digital_pdf` | PDF with a real text layer | the text extraction path |
| `make_short_text_pdf` | PDF with a single very short text layer | short text is trusted, not OCR'd |
| `make_scanned_pdf` | Image-only PDF (no text layer) | the OCR path |
| `make_mixed_pdf` | Digital + scanned pages merged | per-page (mixed) routing |
| `make_garbled_pdf` | Text layer of control chars | low alphanumeric-ratio classification |
| `make_docx` | DOCX with heading/paragraph/list/table (optional image) | order-preserving DOCX extraction |
| `make_encrypted_pdf` | Password-protected PDF | `EncryptedDocumentError` |
| `make_truncated_pdf` | Broken PDF trailer | `CorruptDocumentError` |
| `make_plain_zip` | ZIP without `word/document.xml` | "not a DOCX" detection |
| `make_binary` | Random bytes | unsupported-type rejection |

Both `tests/pipeline/conftest.py` and `tests/api/conftest.py` expose these as
pytest fixtures. The API conftest also adds `api_client` (DRF `APIClient`), and
a `_tmp_media` autouse fixture that redirects `MEDIA_ROOT` into `tmp_path`
(test uploads never touch the repo's `media/`) and forces `OCR_ENGINE=mock` /
zero OCR latency so the API tests are deterministic, plus a
`processed_document` fixture that uploads + processes synchronously and the
shared `_upload` helper.

### 6.3 What each test file covers

**Pure-Python pipeline tests — `backend/tests/pipeline/` (55)**

| File | What it verifies |
| ---- | ---------------- |
| `test_probe.py` | Magic-byte sniffing: DOCX renamed `.pdf` is still DOCX (and warns); PDF renamed `.docx` is still PDF; a plain ZIP is not a DOCX; random bytes are unsupported; empty files raise `EmptyDocumentError`; declared extension captured; no-extension files produce no warning |
| `test_pdf.py` | PDF planning/routing: all-text, all-OCR, and mixed PDFs produce the right per-page strategies; **only scanned pages are sent to OCR** (a `FakeOcrClient` records calls); method is `pdf_text`/`pdf_ocr`/`pdf_mixed`; blocks carry `page` + `metadata.method`, OCR blocks carry confidence; low confidence adds warnings; encrypted/truncated PDFs raise; progress is monotonic and within 0..1; pipeline output merges probe warnings |
| `test_docx.py` | Document-order interleaving (heading → paragraph → list items → table → paragraph); heading level metadata; table `rows` metadata and tab-joined text; page fields null and method `docx`; embedded-image warning (and its absence); corrupt DOCX raises; plain ZIP is not handled |
| `test_pdf_classifier.py` | The per-page text/OCR classifier: long clean text is text; sparse text over an embedded image is OCR; short clean text with no image is text; empty/whitespace is OCR; garbled (low alnum ratio) is OCR; chars/ratio reported |
| `test_ocr.py` | The Tesseract OCR wrapper with `pytesseract` stubbed: returns text + normalized mean confidence (ignoring `-1` tokens); zero confidences handled; language and `--psm` passed through |
| `test_registry_and_renderers.py` | Registry `describe()` contract; unsupported kind raises `UnsupportedFormatError`; `route()` returns extractor + plan; **a toy `TxtExtractor` registered in-test proves a new format needs only one new class**; the Markdown renderer (headings, lists, tables, page markers, pipe escaping), plus the HTML renderer (escaped text, grouped lists, tables, page breaks) and CSV renderer (header row, one row per block, OCR confidence) |

**Django/API tests — `backend/tests/api/` (54, Postgres)**

| File | What it verifies |
| ---- | ---------------- |
| `test_upload.py` | Upload lifecycle: PDF/DOCX → `202 queued`; wrong extension accepted **with warning**; unsupported → `415 unsupported_type`; empty file → `400`; missing `file` field → `400`; oversize → `413 too_large`; duplicate SHA-256 returns the **same id** with `duplicate: true` and creates no second Document/Job; list/retrieve; delete (`204`, then `404`); missing → `404 not_found`; pagination envelope |
| `test_content.py` | Content endpoint: `format=json` block shape + `metadata.method`; `markdown` page markers; `text`; `html` (content-type + page breaks); `csv` (header row); unknown format → `400`; `download=1` sets `Content-Disposition`; **a short real-text PDF is extracted as `pdf_text`, not OCR (regression)**; `page=` filtering; `page=` on a page-less DOCX → `400`; content before done → `409 not_ready`; download returns bytes starting `%PDF-`; search returns headline markers `⟦ ⟧` and the full result shape; search requires `q` ≥ 2 chars; `/api/config/` advertises pdf+docx; the Document serializer's exact contract fields |
| `test_ocr_engine.py` | `build_ocr_client()` selects `MockOcrClient` for `OCR_ENGINE=mock`, `TesseractOcrClient` for `tesseract` when the binary is present, and falls back to mock when it is missing |
| `test_failures.py` | Failure semantics: corrupt and encrypted PDFs fail permanently (`error_code`, `attempts == 1`, no retry); an injected `RuntimeError` is transient — retried up to `WORKER_MAX_ATTEMPTS`, then `internal` with a "Retrying" progress event; raising the cap retries further; a failed document emits a `failed` `ProgressEvent` |
| `test_queue.py` | Queue correctness: sequential claims return different jobs and then `None`; stale `running` jobs (lock older than `WORKER_STALE_AFTER_SECONDS`) are re-queued; fresh ones are not; **three real threads racing to claim never get the same job** (`SELECT … FOR UPDATE SKIP LOCKED`) — uses `transaction=True` with a `threading.Barrier` |
| `test_sse.py` | SSE endpoint via Django's `AsyncClient`: a terminal document emits `event: done` and closes; a queued document streamed while a **background thread** processes it ends with `done`; a failed document emits `event: failed`; an unknown id emits `failed`; headers include `Cache-Control: no-cache` and `X-Accel-Buffering: no` |
| `test_admin.py` | Django admin login page loads and `/static/admin/css/base.css` is served (admin stays styled under uvicorn) |
| `test_agent_tools.py` | Agent tools: schema listing order; `search_documents`, `list_documents`, `get_document` (json + markdown), `get_document_page`; structured `{"error": ...}` for unknown tool / bad query / wrong argument types instead of raising; missing `name` → `400` |

**Frontend tests — `frontend/src/**/*.test.ts(x)` (24)**

| File | What it verifies |
| ---- | ---------------- |
| `components/StatusBadge.test.tsx` | Badge renders each status with the right class; `ProgressBar` shows percent, sets `aria-valuenow`/`aria-label`, and clamps to 0..100 |
| `components/UploadDropzone.test.tsx` | Accepts supported files; rejects unsupported extensions and oversize files (with messages); the dropzone is focusable |
| `components/ContentViewer.test.tsx` | Renders blocks in the preview tab; exposes every export format as a tab (Preview/HTML/Markdown/Plain text/CSV/JSON); lazily fetches a text format and displays it; download links request `download=1` |
| `hooks/useDocumentEvents.test.tsx` | With a fake `EventSource`: opens the stream; on error **falls back to polling**, patches the React Query cache, and stops polling once terminal; a `done` event closes the stream and updates the cache |
| `hooks/useUploadQueue.test.tsx` | Upload queue tracks per-file **byte progress** via the `uploadDocument` callback, then transitions to `accepted`/`duplicate`/`rejected` |
| `lib/highlight.test.ts` | `splitHeadline` parses `⟦ ⟧` markers into match/non-match segments, handles multiple and unbalanced markers, and keeps `<script>` text inert (no HTML injection) |

### 6.4 Testing techniques worth noting

- **Fake OCR over mocks of the pipeline** — `test_pdf.py` injects a
  `FakeOcrClient` that *records which pages it was called for*, proving the
  router honours the per-page plan rather than just asserting the output.
- **Fault injection** — `test_failures.py` uses `monkeypatch` to make
  `PdfExtractor.plan` raise, exercising the retry/back-off path deterministically.
- **Real concurrency** — `test_queue.py` uses actual threads and a barrier
  against real Postgres transactions; `test_sse.py` runs a real background
  thread while the async SSE stream is consumed. These are the tests that drop
  and recreate the test database, hence `--create-db` if a run is interrupted.
- **Contract assertions** — several tests assert the *exact* serializer and
  block key sets, so an accidental contract change fails loudly.
- **Warning-as-error** — pytest is configured to error on warnings, and SSE
  tests explicitly close DB connections/executors so nothing leaks past a test.
- **No committed binaries** — documents are generated per-test, keeping the
  repo clean and tests hermetic.

---

## 7. Documented limitations (by design)

- **No authentication** — take-home demo; the admin panel is the only
  credentials-protected surface.
- **Local disk storage** — raw files live on the `media` volume. The pipeline
  already consumes filesystem paths (`documents/storage.py`), so moving to
  object storage (S3) is a storage-backend change only.
- **DB-backed job queue** — fine at this scale; a dedicated queue is the next
  step.
- **OCR engine** — real OCR runs through Tesseract (bundled in the image);
  other engines plug in behind the `OcrClient` interface with no pipeline
  changes. Accuracy/speed is bounded by the Tesseract model and the render DPI.
- **SSE fan-out** — progress is read per client from Postgres rather than
  pushed through a broker; fine for small concurrency, the trade-off is one
  poll per client per 0.5 s.