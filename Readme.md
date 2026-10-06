# Document Ingestion Pipeline

A document-ingestion pipeline with a React frontend and a Django backend. Users
upload `.pdf` and `.docx` files; the backend routes each file to the right
extractor (digital-text PDF pages vs scanned PDF pages needing OCR vs DOCX),
extracts content into a normalised block structure, stores it in Postgres with
full-text search, and exposes it via a REST API and an agent-tool interface.
The UI shows live processing progress (SSE) and the extracted results.

Adding a new format (e.g. `.txt`) is cheap: one new `Extractor` class,
registered, nothing else changes. Upload validation and the frontend's
accepted-file list both derive from the extractor registry via
`GET /api/config/`.

> The original assessment brief (later replaced by this document) is preserved
> in git history: `git show 857512e:Readme.md`.
>
> **This README is self-contained** — it has everything needed to start the
> stack and run the tests.

## Quick start (Docker)

> Run every command in this README from the **repository root** (the folder
> containing `docker-compose.yml` and `Makefile`).

Requires Docker + Docker Compose (v2) only — no Python, Node, or Postgres on
the host. One command builds and runs everything:

```bash
docker compose up --build -d      # or: make up
```

- Frontend / SPA: <http://localhost:8080>
- Backend API: <http://localhost:8000/api/>
- Django admin: <http://localhost:8000/admin/> (also proxied at <http://localhost:8080/admin/>)

`docker compose up` starts four services:

| Service  | What it runs                                   |
| -------- | ---------------------------------------------- |
| `db`     | Postgres 16 (with healthcheck)                 |
| `backend`| uvicorn (ASGI), runs migrations on start       |
| `worker` | `python manage.py run_worker` (job queue)      |
| `frontend`| multi-stage Node build served by nginx        |

A shared named volume (`media`) holds uploaded raw files and is mounted into
both `backend` and `worker`.

The admin page is styled: Django serves `/static/` itself (wired into
`config/urls.py`, since uvicorn does not serve static files like `runserver`
does), and the frontend nginx proxies both `/admin/` and `/static/` to the
backend. The Docker entrypoint also runs `collectstatic --noinput`.

To stop:

```bash
docker compose down               # or: make down
```

To stop **and** delete all data (database + uploaded files):

```bash
docker compose down -v            # or: make clean
```

To create a Django admin login (optional):

```bash
docker compose exec backend python manage.py createsuperuser
```

## Architecture

```
Browser (React SPA)
   │  /api/*  (REST + SSE)
   ▼
nginx (serves SPA build, proxies /api, buffering off for SSE)
   ▼
Django ASGI (uvicorn) ───────► Postgres ◄─────── Worker (manage.py run_worker)
   │  DRF views + async SSE view     ▲                    │
   │                                 │                    ▼
   └──► media volume (raw files) ◄───┴────────── pipeline/ (pure Python)
                                                 router → extractor → blocks
```

### Request lifecycle

1. **Upload** — The browser streams the file to `POST /api/documents/` (one
   POST per file, at most three concurrent) via XHR so the upload panel shows a
   live per-file **byte-progress bar**; once accepted the same row switches to
   the document's **processing progress** (SSE). The view writes it to a temporary
   file while hashing (SHA-256) and enforcing `MAX_UPLOAD_BYTES` (413
   `too_large`). The file is sniffed with `pipeline/probe.py` — never trusting
   the extension — and rejected with 415 `unsupported_type` if no extractor
   handles the sniffed kind. If the SHA-256 already exists the existing
   document is returned with `duplicate: true`. Otherwise a `Document` row and
   a queued `Job` are created in one transaction (202 Accepted).
2. **Queue** — `run_worker` claims jobs with
   `SELECT … FOR UPDATE SKIP LOCKED` (see `documents/queue.py`), so multiple
   workers would never process the same job. Stale `running` jobs (lock older
   than `WORKER_STALE_AFTER_SECONDS`) are re-queued.
3. **Pipeline** — `process_job` runs the pure-Python `pipeline.service.run_pipeline`
   on a local filesystem path. Progress is reported through a
   `DbProgressReporter` that updates the denormalised `Document.stage/progress`
   columns and appends `ProgressEvent` rows (throttled).
4. **Indexing** — inside one transaction the document's old blocks are deleted,
   new blocks are `bulk_create`d, and the `search` `SearchVectorField` is
   populated. The document is marked `done` with `progress: 1.0` and a final
   `done` SSE event is emitted.
5. **Live progress** — the UI opens an `EventSource` on
   `GET /api/documents/{id}/events/` (a plain async Django view, polled every
   0.5 s, keepalive every 15 s). Each event patches the react-query caches. If
   the stream fails the UI falls back to polling the document every 1.5 s until
   it is terminal.
6. **Retrieval** — `GET /api/documents/{id}/content/` serves blocks as
   `json`, `markdown`, `text`, `html`, or `csv` (optionally per page, or as a
   `download=1` attachment). Search uses Postgres
   full-text search with `websearch` syntax and headline snippets whose matches
   are wrapped in `⟦`/`⟧` sentinels — the frontend renders `<mark>` from those,
   never HTML.

### Routing and the page classifier

Routing is two-layer (`pipeline/router.py`):

1. The **router** picks an extractor from the sniffed file kind (`pdf`, `docx`).
2. The extractor's **`plan()`** makes finer decisions. For PDFs, `PdfExtractor.plan`
   opens the file, decrypts if possible (else `EncryptedDocumentError`), and
   classifies **each page** as `text` or `ocr` via `pipeline/extractors/pdf_classifier.py`.

A page is classified as `ocr` (scanned) when it has no text layer, its text is
too garbled, or it has only a *sparse* text layer **and** an embedded image
(short text over an image ⇒ scanned). A short-but-clean text page with no image
is treated as digital text — so terse pages like a title (`Hello world`) are not
needlessly OCR'd:

| Threshold        | Default | Meaning                                          |
| ---------------- | ------- | ------------------------------------------------ |
| `min_chars`      | `8`     | below this (with an embedded image) → `ocr`      |
| `min_alnum_ratio`| `0.50`  | alphanumeric+whitespace ratio below this → `ocr` (mangled font encodings) |
| `ocr_min_confidence` | `0.60` | OCR results below this add a warning per page |
| `render_scale`   | `3.0`   | pypdfium2 render scale for OCR input images (~216 DPI) |

OCR uses **Tesseract** locally (via `pytesseract`), selected by `OCR_ENGINE`
(`tesseract` by default, or `mock` for tests). If the `tesseract` binary is
missing the backend logs a warning and falls back to the mock client. Swapping
in a cloud engine (Textract/Azure Document Intelligence) means one new
`OcrClient` implementation — no pipeline changes.

The detecting stage therefore reports e.g. *"PDF: 9 text pages, 3 scanned
pages → OCR"* and the UI shows it. The overall method is `pdf_text`,
`pdf_ocr`, or `pdf_mixed`. Each block records `metadata.method` (`text`/`ocr`)
and, for OCR, `metadata.confidence`.

### Structure typing (title / paragraph / list / table)

Extracted content is not flat text — blocks are typed so every output format can
differentiate them:

- **DOCX** — `heading` (with `metadata.level`), `list_item` and `table` come
  from the document's paragraph/table styles; everything else is `paragraph`.
- **PDF** — for digital pages the extractor reads the PDF's own layout
  (per-fragment font size, weight and `x`/`y` position) and infers:
  - **`heading`** — lines larger than the body font (level 1 = largest) or
    short bold standalone lines, with `metadata.level`;
  - **`list_item`** — lines starting with a bullet glyph or `1.` / `a)` marker
    (the marker is stripped from the text);
  - **`paragraph`** — consecutive lines reflowed into one block, split where the
    vertical gap is much larger than the median line spacing.

The four block types (`heading`, `paragraph`, `list_item`, `table`) are then
rendered distinctly by every format: Markdown (`#`, `-`, pipes), HTML
(`<h1>`, `<ul><li>`, `<table>`), plain text (`#`, `*`, tabs), CSV (a `type`
column) and JSON (`type` + `metadata`). The UI's **Preview** tab applies the
same headings, lists and tables.

## API reference

All endpoints are under `/api/`. Errors always use
`{"error": {"code": str, "message": str}}` with codes `bad_request` (400),
`not_found` (404), `not_ready` (409), `too_large` (413), `unsupported_type`
(415). There is no authentication (see Limitations).

| Endpoint | Method | Description |
| --- | --- | --- |
| `documents/` | POST | Upload (multipart field `file`). `202` new / `200` duplicate with `{"document": Document, "duplicate": bool}` |
| `documents/` | GET | Paginated list: `{count, next, previous, results: Document[]}` |
| `documents/{id}/` | GET | Single document |
| `documents/{id}/` | DELETE | Delete document and stored file (204) |
| `documents/{id}/content/?format=json\|markdown\|text\|html\|csv&page=N&download=1` | GET | Content (json/markdown/text/html/csv). `409 not_ready` unless `status=done`; `400` if `page` given on a page-less document; `download=1` sets `Content-Disposition: attachment` |
| `documents/{id}/download/` | GET | Original file download |
| `documents/{id}/events/` | GET | SSE stream: `event: progress\|done\|failed`, `data: {status, stage, progress, message}` |
| `search/?q=&limit=` | GET | Full-text search. Headlines wrap matches in `⟦ ⟧` |
| `config/` | GET | `{max_upload_bytes, supported: [{kind, extensions, mime_types}]}` |
| `agent/tools/` | GET | OpenAI-style function schemas |
| `agent/tools/call/` | POST | `{name, arguments}` → JSON result |

### Error codes

| HTTP | `error.code` | Meaning |
| --- | --- | --- |
| 400 | `bad_request` | missing `file`, empty file, bad `page`, bad query/format |
| 404 | `not_found` | unknown document id |
| 409 | `not_ready` | content requested before `status=done` |
| 413 | `too_large` | file exceeds `MAX_UPLOAD_BYTES` |
| 415 | `unsupported_type` | sniffed kind has no registered extractor |

A failed document's `error_code` is one of `corrupt`, `encrypted`,
`unsupported`, `empty` (permanent, never retried) or `internal` (transient,
retried up to `WORKER_MAX_ATTEMPTS` then failed).

### Document shape

```json
{
  "id": "uuid", "filename": "a.pdf", "mime": "application/pdf",
  "size": 123, "sha256": "…",
  "status": "queued|processing|done|failed",
  "stage": "queued|detecting|extracting|indexing|done|failed",
  "progress": 0.4,
  "method": "" | "pdf_text" | "pdf_ocr" | "pdf_mixed" | "docx",
  "page_count": 3, "block_count": 12,
  "warnings": ["…"],
  "error": "", "error_code": "" | "corrupt" | "encrypted" | "unsupported" | "empty" | "internal",
  "created_at": "…", "updated_at": "…"
}
```

### Block shape

```json
{
  "id": 1, "idx": 0,
  "type": "heading|paragraph|list_item|table",
  "text": "…", "page": 1,
  "metadata": { "method": "text|ocr", "confidence": 0.92, "level": 2, "rows": [["a","b"]] }
}
```

## Agent tool interface

`GET /api/agent/tools/` returns four OpenAI-style function schemas:
`search_documents`, `list_documents`, `get_document`, `get_document_page`.
They share the same retrieval code as the REST API. Bad arguments return a
structured `{"error": ...}` instead of raising.

Example call:

```bash
curl -s -X POST http://localhost:8000/api/agent/tools/call/ \
  -H 'Content-Type: application/json' \
  -d '{"name": "search_documents", "arguments": {"query": "invoice total"}}'
```

```json
{
  "query": "invoice total",
  "count": 2,
  "results": [
    {
      "document_id": "…", "filename": "invoice.pdf", "block_id": 41,
      "idx": 3, "page": 2, "type": "paragraph",
      "headline": "The ⟦invoice total⟧ was £412.50 …", "rank": 0.9
    }
  ]
}
```

## How to add a new format

Extractors self-describe and are the only thing that changes. Example: support
plain `.txt` files by creating a `TxtExtractor` (shown here for documentation
only — **do not** register it unless you actually add the feature):

```python
# backend/pipeline/extractors/txt.py
from ..errors import EmptyDocumentError
from ..schema import Block, ExtractionPlan, ExtractionResult


class TxtExtractor:
    name = "txt"
    kinds = frozenset({"txt"})
    extensions = (".txt",)
    mime_types = ("text/plain",)

    def can_handle(self, probe):
        # plain text has no magic bytes; sniffing yields kind=None, so fall
        # back to the declared extension.
        return probe.kind == "txt" or (probe.kind is None and probe.declared_ext == ".txt")

    def plan(self, probe):
        return ExtractionPlan(extractor="txt", units=1, strategies=["text"], summary="TXT")

    def extract(self, probe, plan, progress):
        text = probe.path.read_text()
        if not text.strip():
            raise EmptyDocumentError("The file is empty.")
        return ExtractionResult(
            blocks=[Block(type="paragraph", text=text, metadata={})],
            method="txt",
            page_count=None,
        )
```

Then register it:

```python
# backend/pipeline/registry.py (default_registry)
from .extractors.txt import TxtExtractor
registry.register(TxtExtractor())
```

That is everything:

- `GET /api/config/` now advertises `.txt`, so the React dropzone accepts it.
- Upload validation accepts it (kind `txt` is in `supported_kinds()`).
- The router selects it automatically.

The pipeline (`probe.py`) only sniffs PDF/DOCX magic bytes; other formats rely
on `can_handle`/`declared_ext` exactly as the txt example above.

## Tests

All tests run in Docker — no host Python or Node needed.

```bash
make test              # backend suite (114) + frontend typecheck/tests (25)
make backend-test      # backend only; starts Postgres for you
make frontend-test     # frontend typecheck + unit tests
```

The backend suite runs inside the project image with the source bind-mounted
and a real Postgres (started automatically). The frontend suite builds the
image's `test` stage. If a backend run is interrupted and leaves a stale test
database, reset it with `docker compose down -v` (or `make clean`) and re-run.

### What the tests check

139 automated tests in total — **114 backend** (59 pipeline + 55 API) and
**25 frontend** — grouped below by suite.

**Backend pipeline core** — `backend/tests/pipeline`, 59 tests, no database:

- **Sniffing** (`test_probe.py`) — a DOCX renamed `.pdf` is still DOCX (and
  warns); a PDF renamed `.docx` is still PDF; a plain ZIP is not a DOCX; random
  bytes are unsupported; empty files raise `EmptyDocumentError`.
- **PDF extraction** (`test_pdf.py`) — per-page routing (text / OCR / mixed);
  **only scanned pages are OCR'd**; methods `pdf_text` / `pdf_ocr` /
  `pdf_mixed`; page + method metadata and OCR confidence; low-confidence
  warnings; encrypted/truncated errors; monotonic progress; and **structure
  typing** (font-size headings with levels, bullet/numbered list items,
  reflowed paragraphs — while a uniform-text PDF stays all-paragraph).
- **DOCX extraction** (`test_docx.py`) — document-order interleaving of
  headings, paragraphs, lists and tables; heading levels; table cell metadata;
  null page fields; embedded-image warnings; corrupt-DOCX errors; plain-ZIP
  rejection.
- **Page classifier** (`test_pdf_classifier.py`) — the text-vs-OCR decision at
  its thresholds: sparse text over an image → OCR, short clean text with no
  image → text, empty/garbled → OCR.
- **OCR wrapper** (`test_ocr.py`) — the Tesseract client (pytesseract stubbed):
  text and normalized mean confidence, `-1` tokens ignored, language/`--psm`
  passed through.
- **Registry & renderers** (`test_registry_and_renderers.py`) — the registry
  contract, unsupported-kind error, routing, that one new extractor is enough
  to add a format, and the Markdown/HTML/CSV renderers (escaping, page markers,
  tables).

**Backend API** — `backend/tests/api`, 55 tests, against Postgres:

- **Upload** (`test_upload.py`) — `202` queued, wrong-extension warning,
  `415 unsupported_type`, `400` empty/missing, `413 too_large`, duplicate
  SHA-256 returns the same id, list/retrieve/delete, `404`, pagination.
- **Content** (`test_content.py`) — json / markdown / text / html / csv,
  `?page=`, `download=1` attachment, unknown format `400`, `409 not_ready`,
  download bytes, search headlines with `⟦ ⟧`, `/api/config/`, the exact
  serializer fields, and that a short real-text PDF is **not** sent to OCR.
- **Failures** (`test_failures.py`) — permanent errors (corrupt/encrypted) fail
  once with an `error_code`; transient errors retry to `WORKER_MAX_ATTEMPTS`
  then fail `internal`, emitting a failed `ProgressEvent`.
- **Queue** (`test_queue.py`) — distinct claims then `None`, stale-lock
  re-queueing, and **three real threads never claim the same job**
  (`SELECT … FOR UPDATE SKIP LOCKED`).
- **SSE** (`test_sse.py`) — emits `done`/`failed` and closes, streams a live
  background job, handles unknown ids, sets the no-buffering headers.
- **OCR engine / admin / agent tools** (`test_ocr_engine.py`, `test_admin.py`,
  `test_agent_tools.py`) — `OCR_ENGINE` selects Tesseract or the mock (with a
  mock fallback); the admin page + static assets load; the four agent tools and
  their structured `{"error": …}` responses.

**Frontend** — `frontend/src/**/*.test.ts(x)`, 25 tests, Vitest + Testing Library:

- **Status/progress** (`StatusBadge.test.tsx`) — badges render per status; the
  progress bar shows the percent, ARIA values, and clamps 0–100.
- **Dropzone** (`UploadDropzone.test.tsx`) — supported files pass through;
  unsupported/oversize files are rejected with messages.
- **Content viewer** (`ContentViewer.test.tsx`) — the preview renders blocks and
  groups list items into a `<ul>`; every export-format tab
  (Preview/HTML/Markdown/Plain text/CSV/JSON) works with `download=1`.
- **Live updates** (`useDocumentEvents.test.tsx`, `useUploadQueue.test.tsx`) —
  the SSE hook patches the cache and **falls back to polling** on error; the
  upload queue tracks per-file **byte progress** then
  accepted/duplicate/rejected.
- **Search** (`highlight.test.ts`) — `⟦ ⟧` headline markers split into `<mark>`
  segments, with HTML kept inert.

## Known limitations

- **No authentication** — this is a take-home demo; anyone can upload, read,
  or delete documents.
- **Local disk storage** — raw files live on a shared `media` volume; the
  pipeline already works from a filesystem path (`documents/storage.py`), so
  moving to S3 means changing the storage backend only.
- **DB-backed job queue** — fine at this scale; a dedicated broker-backed queue
  would be the next step.
- **Local OCR** — real OCR runs through Tesseract (`pipeline/ocr/tesseract.py`)
  behind the `OcrClient` interface; `OCR_ENGINE=mock` (used by the test suite)
  returns canned text. A cloud engine would be one new `OcrClient`, with no
  pipeline changes.
- **No virus scanning** of uploads.
- **SSE fan-out** — progress events are read per-client from Postgres rather
  than pushed via a broker.

## Troubleshooting

- **First `docker compose up --build` is slow / needs network** — the images
  pull base layers and install Tesseract (apt), Python (pip) and Node (npm)
  dependencies. Subsequent builds are cached.
- **Ports already in use** — stop whatever is on `8080`, `8000` or `5432`, or
  change the mappings in `docker-compose.yml`.
- **`ModuleNotFoundError: No module named 'pytest'`** — you're running `pytest`
  on the host. Use `make backend-test`, which runs in Docker.
- **`database "test_documents" already exists`** — reset with
  `docker compose down -v` (or `make clean`) and re-run.
- **Upload returns 500 `PermissionError: /media`** — rebuild the images:
  `docker compose build backend worker`.
- **Reset everything** — `docker compose down -v` (or `make clean`) deletes the
  database volume and uploaded files.