"""Worker loop: requeue stale -> claim -> process, forever."""

from __future__ import annotations

import logging
import signal
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from documents.processing import process_job
from documents.queue import DbJobQueue

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Process queued document jobs."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--once", action="store_true", help="Process a single job and exit.")
        parser.add_argument("--drain", action="store_true", help="Exit when the queue is empty.")

    def handle(self, *args, **options) -> None:
        queue = DbJobQueue()
        self._stop = False

        def _stop_handler(signum, frame):
            self._stop = True

        signal.signal(signal.SIGINT, _stop_handler)
        signal.signal(signal.SIGTERM, _stop_handler)

        while not self._stop:
            try:
                requeued = queue.requeue_stale()
                if requeued:
                    logger.info("Requeued %d stale job(s)", requeued)
            except Exception:  # noqa: BLE001
                logger.exception("requeue_stale failed")

            job = None
            try:
                job = queue.claim()
            except Exception:  # noqa: BLE001
                logger.exception("claim failed")

            if job is None:
                if options["once"] or options["drain"]:
                    self.stdout.write("Queue empty; exiting.")
                    break
                time.sleep(settings.WORKER_POLL_INTERVAL)
                continue

            logger.info("Processing job %s (%s)", job.id, job.document.filename)
            try:
                process_job(job, queue)
            except Exception:  # noqa: BLE001 - process_job should never raise
                logger.exception("process_job escaped for job %s", job.id)
            logger.info("Finished job %s", job.id)

            if options["once"]:
                break

        self.stdout.write("Worker stopped cleanly.")