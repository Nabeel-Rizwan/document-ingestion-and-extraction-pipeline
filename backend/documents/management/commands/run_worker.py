"""Worker loop: requeue stale -> claim -> process, forever."""

# Enable postponed evaluation of annotations (PEP 563).
from __future__ import annotations

# logging emits structured worker status/exception messages.
import logging
# signal lets us install SIGINT/SIGTERM handlers for graceful shutdown.
import signal
# time.sleep throttles polling when the queue is empty.
import time

# settings supplies the worker poll interval.
from django.conf import settings
# BaseCommand is the base class for custom management commands.
from django.core.management.base import BaseCommand

# process_job runs a claimed job through the pipeline.
from documents.processing import process_job
# DbJobQueue is the database-backed work queue.
from documents.queue import DbJobQueue

# Module-level logger for this command.
logger = logging.getLogger(__name__)


class Command(BaseCommand):
    # Description shown by ``manage.py help``.
    help = "Process queued document jobs."

    def add_arguments(self, parser) -> None:
        # --once processes at most one job then exits.
        parser.add_argument("--once", action="store_true", help="Process a single job and exit.")
        # --drain exits as soon as the queue is found empty.
        parser.add_argument("--drain", action="store_true", help="Exit when the queue is empty.")

    def handle(self, *args, **options) -> None:
        # Instantiate the database-backed queue.
        queue = DbJobQueue()
        # Shutdown flag flipped by the signal handler.
        self._stop = False

        def _stop_handler(signum, frame):
            # Request a clean stop on the next loop iteration.
            self._stop = True

        # Trap Ctrl-C and termination signals for graceful shutdown.
        signal.signal(signal.SIGINT, _stop_handler)
        signal.signal(signal.SIGTERM, _stop_handler)

        # Main worker loop until a stop is requested.
        while not self._stop:
            try:
                # Return jobs whose leases have expired back to the queue.
                requeued = queue.requeue_stale()
                # Log how many stale jobs were recovered, if any.
                if requeued:
                    logger.info("Requeued %d stale job(s)", requeued)
            except Exception:  # noqa: BLE001
                # A requeue failure must not kill the worker; log and continue.
                logger.exception("requeue_stale failed")

            # Job claimed this iteration, if any.
            job = None
            try:
                # Atomically claim the next available job.
                job = queue.claim()
            except Exception:  # noqa: BLE001
                # A claim failure must not kill the worker; log and continue.
                logger.exception("claim failed")

            # No work available right now.
            if job is None:
                # In single-shot or drain mode, exit when the queue is empty.
                if options["once"] or options["drain"]:
                    self.stdout.write("Queue empty; exiting.")
                    break
                # Otherwise sleep briefly and poll again.
                time.sleep(settings.WORKER_POLL_INTERVAL)
                continue

            # Announce the job being processed.
            logger.info("Processing job %s (%s)", job.id, job.document.filename)
            try:
                # Execute the job; process_job owns its own error handling.
                process_job(job, queue)
            except Exception:  # noqa: BLE001 - process_job should never raise
                # Defensive catch so an unexpected escape cannot crash the worker.
                logger.exception("process_job escaped for job %s", job.id)
            # Confirm completion of the job.
            logger.info("Finished job %s", job.id)

            # In --once mode stop after the single processed job.
            if options["once"]:
                break

        # Final message once the loop has exited.
        self.stdout.write("Worker stopped cleanly.")