"""Server-Sent Events endpoint.

A plain Django async view (not DRF) streaming progress for a document. Uses the
async ORM only. Clients can resume via the ``Last-Event-ID`` header.
"""

from __future__ import annotations

import asyncio
import json
import time

from django.core.exceptions import ValidationError
from django.http import StreamingHttpResponse

from ..models import Document, ProgressEvent

POLL_INTERVAL = 0.5
KEEPALIVE_INTERVAL = 15.0


def _sse_event(event_id: int | None, event: str, data: dict) -> str:
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data)}")
    return "\n".join(lines) + "\n\n"


async def sse_view(request, pk):
    async def event_stream():
        try:
            doc = await Document.objects.aget(pk=pk)
        except (Document.DoesNotExist, ValidationError):
            yield _sse_event(
                None,
                "failed",
                {"status": "failed", "stage": "failed", "progress": 1.0, "message": "Document not found"},
            )
            return

        last_id = 0
        try:
            last_id = int(request.headers.get("Last-Event-ID", "0") or "0")
        except ValueError:
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

        last_keepalive = time.monotonic()
        try:
            while True:
                new_events = []
                async for e in ProgressEvent.objects.filter(document=doc, id__gt=last_id).order_by("id"):
                    new_events.append(e)

                for e in new_events:
                    last_id = e.id
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

                fresh = await Document.objects.aget(pk=pk)
                if fresh.status in ("done", "failed"):
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

                if time.monotonic() - last_keepalive > KEEPALIVE_INTERVAL:
                    yield ": keepalive\n\n"
                    last_keepalive = time.monotonic()

                await asyncio.sleep(POLL_INTERVAL)
        except asyncio.CancelledError:
            # Client disconnected; stop cleanly.
            return

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response