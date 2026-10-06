# ANSWERS

Prepared discussion notes for the three follow-up questions. They describe how
the pipeline implemented in this repository would evolve, and call out which
parts of the current design already anticipate the change.

## Scalable production architecture

The repository is a deliberately small, single-node-shaped system; the seams
are drawn so each piece can be replaced independently in production.

**Current shape (for reference)**

```
Browser ─▶ nginx ─▶ Django ASGI ─┬─▶ Postgres  ◀─┐
                                 │   (data + queue)│
                                 └─▶ media vol     └─ worker (run_worker) ─▶ pipeline/
```

The important abstractions are: a `JobQueue` Protocol (`documents/queue.py`),
an `Extractor` registry (`pipeline/registry.py`), an `OcrClient` Protocol
(`pipeline/ocr/base.py`), a `ProgressReporter` Protocol, and a filesystem
`local_path()` storage seam (`documents/storage.py`). Everything below swaps
implementations behind those seams.

**Production target**

- **Object storage instead of a shared volume.** Raw files go to S3/GCS.
  Uploads are presigned so bytes never stream through the API; extraction uses
  a short-lived download or a mounted read. Only `documents/storage.py` changes.
- **A real broker instead of the DB-as-queue.** Publish a job id to SQS /
  RabbitMQ / Redis Streams and run an autoscaling worker fleet (KEDA/ASG on
  queue depth). Keep the current `DbJobQueue` as the local/dev implementation.
- **Stateless, horizontally scaled API.** Multiple uvicorn/gunicorn ASGI pods
  behind a load balancer. Because SSE currently reads progress from Postgres
  per client, at scale move progress fan-out to Redis pub/sub (or a managed
  event service) and keep Postgres for durable history only. Sticky sessions or
  a shared pub/sub are required for SSE.
- **Separate the extraction/OCR workload.** OCR is CPU/GPU-heavy; run it in its
  own pool so an OCR backlog can never starve the API. Use Cloud OCR
  (Textract / Azure Document Intelligence) or self-hosted Tesseract/PaddleOCR,
  all behind the existing `OcrClient`.
- **Database scaling.** Postgres primary + read replicas; PgBouncer for
  connection pooling; partition `Job` and `ProgressEvent` by time and archive
  terminal progress rows. At high search volume move full-text search to
  OpenSearch/Elasticsearch (the retrieval API stays the same).
- **Reliability.** Idempotency via the content SHA-256 (already used for
  dedupe), at-least-once delivery with per-job retries + exponential backoff and
  a dead-letter queue, plus the existing stale-lock recovery
  (`requeue_stale`). Poison messages fail fast with a permanent `error_code`.
- **Multi-tenancy & security.** Authentication/authorization (OIDC/JWT),
  per-tenant object prefixes and row-level scoping, malware scanning on upload,
  signed URLs, and encryption in transit and at rest.
- **Operability.** Structured logs, metrics/tracing, SLOs (ingest latency,
  queue age, OCR error rate), CI/CD with migrations as a separate pre-deploy
  job, and load testing. Add per-tenant rate limiting and backpressure (429/202).

## Supporting plain text files

This is the cheap case the design was built for: **one new extractor, nothing
else changes.** Because `GET /api/config/` derives upload validation and the
frontend dropzone's accepted list from the registry, adding the class is
sufficient.

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
        # Plain text has no magic bytes, so sniffing yields kind=None; fall
        # back to the declared extension.
        return probe.kind == "txt" or (
            probe.kind is None and probe.declared_ext == ".txt"
        )

    def plan(self, probe):
        return ExtractionPlan(extractor="txt", units=1,
                              strategies=["text"], summary="Plain text")

    def extract(self, probe, plan, progress):
        raw = probe.path.read_bytes()
        text = raw.decode(self._encoding(raw), errors="replace")
        if not text.strip():
            raise EmptyDocumentError("The file is empty.")
        blocks = [Block(type="paragraph", text=p.strip(), metadata={})
                  for p in text.split("\n\n") if p.strip()]
        return ExtractionResult(blocks=blocks, method="txt", page_count=None)

    @staticmethod
    def _encoding(raw):
        # Prefer UTF-8; fall back to a detector (charset-normalizer) for the
        # long tail, and strip a UTF-8 BOM if present.
        try:
            raw.decode("utf-8")
            return "utf-8-sig"
        except UnicodeDecodeError:
            return "latin-1"
```

Then register it in `pipeline/registry.py::default_registry`:

```python
from .extractors.txt import TxtExtractor
registry.register(TxtExtractor())
```

Beyond `.txt`, the same block model absorbs related formats:

- **`.md` / `.markdown`** — parse ATX headings/lists into `heading`/
  `list_item` blocks (a tiny parser, or `markdown-it-py` for tokens).
- **`.csv` / `.tsv`** — one `table` block with `metadata.rows`, matching the
  DOCX table shape, so it flows through the same renderers.
- **`.html`** — extract text with heading/list structure (`selectolax`/
  BeautifulSoup); treat it as untrusted and store text only.
- **`.xlsx` / `.pptx`** — new extractors that emit `table`/`heading` blocks;
  `.pptx` also needs image rendering for slide OCR.

Pipeline-level details: text has no magic bytes, so `probe.py` keeps
`kind=None` and relies on `declared_ext`; line endings are normalised
(`\r\n`→`\n`); encoding detection matters; empty files map to the existing
`empty` error code. Search, the content API, and all output formats
(json/markdown/text/html/csv) then work unchanged.

## 100x upload volume

100x is a load problem, not a correctness one — the same seams absorb it.

- **Ingest path.** Presigned direct-to-object-storage uploads remove the API
  from the byte path. Keep the SHA-256 dedupe so repeated files are no-ops.
  Return `202` and let the queue absorb bursts; shed load with `429` when
  needed.
- **Queue + workers.** Queue depth drives autoscaling of a dedicated worker
  fleet; a DLQ plus backoff handles retries. OCR runs in its own pool (or
  fully managed cloud OCR) so it scales — and costs — independently of text
  extraction.
- **Database.** Write amplification is the main risk. Partition `Job` and
  `ProgressEvent` by time, batch inserts (`bulk_create` is already used for
  blocks), throttle progress writes (already coalesced in
  `DbProgressReporter`), and move progress fan-out off Postgres to Redis
  pub/sub. Add read replicas for list/search reads and PgBouncer for pooling.
- **Search.** Shift full-text search to OpenSearch/Elasticsearch and index
  asynchronously; add pgvector/embeddings later for semantic retrieval. The
  `documents/services.py` retrieval layer is the single place to change.
- **Storage/cost.** Lifecycle raw files to cold storage; keep original + derived
  content cheaply retrievable. 100x OCR is a real cost — prefer text-layer
  extraction first (already done) and only OCR pages that need it.
- **Protection.** Per-tenant rate limits and quotas, fair queueing so one tenant
  cannot starve others, idempotent consumers, and clear backpressure signals.
- **Observability.** Track queue age, per-stage latency, OCR failure rate and
  DLQ depth as SLOs; load test with representative PDFs (large, scanned, mixed)
  and scale on the metrics, not on guesswork.

**In one line:** the current system already isolates the three things that need
to scale — the extraction code (`pipeline/`), the OCR engine (`OcrClient`), and
the queue (`JobQueue`) — behind protocols; production replaces each
implementation and moves raw files to object storage, leaving the rest of the
architecture intact.
