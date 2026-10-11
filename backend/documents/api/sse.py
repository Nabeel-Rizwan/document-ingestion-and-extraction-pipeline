"""Server-Sent Events endpoint.

A plain Django async view (not DRF) streaming progress for a document. Uses the
async ORM only. Clients can resume via the ``Last-Event-ID`` header.
"""

# Enable postponed evaluation of annotations (PEP 563).
from __future__ import annotations

# asyncio provides sleep and is used for cooperative async cancellation handling.
import asyncio
# json serializes event payloads into the SSE ``data:`` line.
import json
# time.monotonic() supplies a steady clock for keepalive timing.
import time

# ValidationError is raised by the ORM when a malformed PK cannot be parsed.
from django.core.exceptions import ValidationError
# StreamingHttpResponse lets the view yield bytes incrementally to the client.
from django.http import StreamingHttpResponse

# Document holds current state; ProgressEvent stores the append-only event log.
from ..models import Document, ProgressEvent

# How often (seconds) the stream polls for new progress events.
POLL_INTERVAL = 0.5
# How often (seconds) to emit a keepalive comment to hold the connection open.
KEEPALIVE_INTERVAL = 15.0


def _sse_event(event_id: int | None, event: str, data: dict) -> str:
    # Accumulate the individual SSE protocol lines for one event.
    lines = []
    # Emit an ``id:`` line only when an event id is known (supports resume).
    if event_id is not None:
        lines.append(f"id: {event_id}")
    # The ``event:`` line names the event type the client dispatches on.
    lines.append(f"event: {event}")
    # The ``data:`` line carries the JSON-encoded payload.
    lines.append(f"data: {json.dumps(data)}")
    # SSE messages are terminated by a blank line ("\n\n").
    return "\n".join(lines) + "\n\n"


async def sse_view(request, pk):
    # Inner async generator produces the SSE byte stream lazily as it is consumed.
    async def event_stream():
        try:
            # Fetch the target document using the async ORM.
            doc = await Document.objects.aget(pk=pk)
        except (Document.DoesNotExist, ValidationError):
            # Unknown (or malformed) PK: emit one terminal "failed" event then close.
            yield _sse_event(
                None,
                "failed",
                {"status": "failed", "stage": "failed", "progress": 1.0, "message": "Document not found"},
            )
            return

        # Highest progress-event id already seen by the client; 0 means "from start".
        last_id = 0
        try:
            # Resume point supplied by the client's Last-Event-ID header.
            last_id = int(request.headers.get("Last-Event-ID", "0") or "0")
        except ValueError:
            # Malformed header value: fall back to replaying from the beginning.
            last_id = 0

        # Already terminal: emit a single event with the current state and close.
        if doc.status in ("done", "failed"):
            yield _sse_event(
                None,
                doc.status,
                {
                    "status": doc.status,
                    "stage": doc.stage,
                    "progress": doc.progress,
                    "message": doc.error or "Done",
                },
            )
            return

        # Timestamp of the last keepalive so we can time the next one.
        last_keepalive = time.monotonic()
        try:
            # Poll indefinitely until the document reaches a terminal state.
            while True:
                # Buffer events fetched this iteration before yielding them.
                new_events = []
                # Query all not-yet-seen events for this document in id order.
                async for e in ProgressEvent.objects.filter(document=doc, id__gt=last_id).order_by("id"):
                    new_events.append(e)

                # Stream each newly observed progress event in order.
                for e in new_events:
                    # Advance the resume cursor to the latest delivered event.
                    last_id = e.id
                    # Terminal statuses become their own event name; others are "progress".
                    event_name = e.status if e.status in ("done", "failed") else "progress"
                    yield _sse_event(
                        e.id,
                        event_name,
                        {
                            "status": e.status,
                            "stage": e.stage,
                            "progress": e.progress,
                            "message": e.message,
                        },
                    )

                # Re-read the document to detect completion that may lack an event.
                fresh = await Document.objects.aget(pk=pk)
                # If the document is now terminal, finish the stream.
                if fresh.status in ("done", "failed"):
                    # Emit a synthetic terminal event only if none was just yielded.
                    if not (new_events and new_events[-1].status in ("done", "failed")):
                        yield _sse_event(
                            None,
                            fresh.status,
                            {
                                "status": fresh.status,
                                "stage": fresh.stage,
                                "progress": fresh.progress,
                                "message": fresh.error or "Done",
                            },
                        )
                    return

                # Emit a keepalive comment if enough idle time has elapsed.
                if time.monotonic() - last_keepalive > KEEPALIVE_INTERVAL:
                    yield ": keepalive\n\n"
                    last_keepalive = time.monotonic()

                # Yield control to the event loop before the next poll.
                await asyncio.sleep(POLL_INTERVAL)
        except asyncio.CancelledError:
            # Client disconnected; stop cleanly.
            return

    # Build the streaming response from the async generator with the SSE content type.
    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    # Prevent caching/proxies from buffering the event stream.
    response["Cache-Control"] = "no-cache"
    # Disable nginx proxy buffering so events are flushed immediately.
    response["X-Accel-Buffering"] = "no"
    return response