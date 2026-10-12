"""SSE endpoint tests.

What it does:
    Verifies the Server-Sent Events stream at /api/documents/<id>/events/:
    terminal docs immediately emit done/failed and close, queued docs stream
    progress then close once a worker finishes, and missing docs emit failed.

How it works:
    - ``_process`` synchronously finishes a doc before streaming; the queued
      test instead processes in a background thread while the main thread
      consumes the stream.
    - ``_consume_stream`` spins a fresh asyncio loop with Django AsyncClient,
      collects streaming chunks to text, then closes DB connections so the
      test DB can be torn down. Needs transaction=True for thread visibility.
"""

from __future__ import annotations

import asyncio

import pytest

from documents.models import Document, Job
from documents.processing import process_job
from documents.queue import DbJobQueue

from tests.api.conftest import _upload


def _process(api_client, path, filename):
    # What: uploads + fully processes one file, returning the DONE Document.
    # How: POSTs via _upload, runs process_job inline on the queued Job.
    resp = _upload(api_client, path, filename)
    doc_id = resp.data["document"]["id"]
    job = Job.objects.get(document_id=doc_id)
    process_job(job, DbJobQueue())
    return Document.objects.get(pk=doc_id)


def _consume_stream(url, timeout=5.0):
    """Consume an SSE stream to completion inside an event loop."""
    # What: helper that GETs an SSE URL and returns (response, full text).
    # How: creates an isolated event loop, uses AsyncClient to stream chunks,
    #   joins them to text, closes asgiref/Django connections + GC so later
    #   teardown doesn't hit "connection already closed" or leaked handles.

    async def run():
        from django.test import AsyncClient

        client = AsyncClient()
        resp = await client.get(url)
        chunks = []
        async for chunk in resp.streaming_content:
            chunks.append(chunk)
        text = b"".join(chunks).decode()
        # close DB connections opened in asgiref's thread-sensitive thread
        from asgiref.sync import sync_to_async
        from django.db import connections

        await sync_to_async(connections.close_all)()
        return resp, text

    loop = asyncio.new_event_loop()
    try:
        coro = asyncio.wait_for(run(), timeout)
        resp, text = loop.run_until_complete(coro)
    finally:
        try:
            loop.run_until_complete(loop.shutdown_default_executor())
        finally:
            loop.close()
        # Close any DB connections opened by the async client so the test
        # database can be dropped afterwards.
        from django.db import connections

        connections.close_all()
        import gc

        gc.collect()
    return resp, text


@pytest.mark.django_db(transaction=True)
def test_sse_terminal_document_sends_event_and_closes(api_client, digital_pdf):
    # What: already-done doc streams a single "done" event with no-cache headers.
    # How: processes first, consumes the events URL, asserts 200 + SSE
    #   headers and that text contains "event: done" + done status JSON.
    doc = _process(api_client, digital_pdf, "doc.pdf")
    resp, text = _consume_stream(f"/api/documents/{doc.id}/events/")
    assert resp.status_code == 200
    assert resp["Cache-Control"] == "no-cache"
    assert resp["X-Accel-Buffering"] == "no"
    assert "event: done" in text
    assert '"status": "done"' in text


@pytest.mark.django_db(transaction=True)
def test_sse_queued_document_streams_then_closes(api_client, digital_pdf):
    """A queued document: consume while a thread processes it; stream must end."""
    # What: live progress - stream stays open while queued, ends with done
    #   once the worker finishes.
    # How: uploads (stays queued), spawns a thread that sleeps 0.3s then
    #   processes the job on its own DB connection, while the main thread
    #   consumes the SSE stream with a 15s timeout; asserts done event.
    resp = _upload(api_client, digital_pdf, "doc.pdf")
    doc_id = resp.data["document"]["id"]

    def process_in_thread():
        import time

        time.sleep(0.3)  # let the SSE consumer subscribe first
        from django.db import connection

        connection.close()  # avoid sharing the main thread's connection
        try:
            job = Job.objects.get(document_id=doc_id)
            process_job(job, DbJobQueue())
        finally:
            connection.close()

    import threading

    t = threading.Thread(target=process_in_thread)
    t.start()
    _, text = _consume_stream(f"/api/documents/{doc_id}/events/", timeout=15.0)
    t.join()

    assert "event: done" in text
    assert "data:" in text


@pytest.mark.django_db(transaction=True)
def test_sse_failed_document_sends_failed_event(api_client, tmp_path):
    # What: failed docs stream a "failed" event with failed status JSON.
    # How: uploads broken bytes, processes to failed, consumes stream and
    #   asserts both the event name and status payload.
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4 broken broken broken broken")
    resp = _upload(api_client, bad, "bad.pdf")
    doc_id = resp.data["document"]["id"]
    job = Job.objects.get(document_id=doc_id)
    process_job(job, DbJobQueue())
    _, text = _consume_stream(f"/api/documents/{doc_id}/events/")
    assert "event: failed" in text
    assert '"status": "failed"' in text


@pytest.mark.django_db(transaction=True)
def test_sse_missing_document(api_client):
    # What: unknown document id still returns a well-formed failed event
    #   (so EventSource clients don't hang).
    # How: consumes events for a random UUID, asserts "event: failed" in text.
    import uuid

    _, text = _consume_stream(f"/api/documents/{uuid.uuid4()}/events/")
    assert "event: failed" in text
