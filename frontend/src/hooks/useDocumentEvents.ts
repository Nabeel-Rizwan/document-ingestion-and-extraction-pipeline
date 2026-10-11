/** Live progress via SSE, with automatic polling fallback.

Opens an EventSource on /api/documents/{id}/events/, patches the react-query
caches on each event, closes on done/failed. On any EventSource error it falls
back to polling GET /api/documents/{id}/ every 1.5s until the document is
terminal.
 */

import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { eventsUrl, getDocument } from "../api/documents";
import type { Document, SseEvent } from "../api/types";
import { documentKey, documentsKey, patchDocumentCaches } from "./useDocuments";

// Statuses that mean no further live updates will ever arrive.
const TERMINAL = new Set(["done", "failed"]);
// Polling interval (ms) used when the SSE stream is unavailable.
const POLL_MS = 1500;

// Subscribe to live document progress while `enabled`; tears down on unmount.
export function useDocumentEvents(id: string, enabled: boolean): void {
  // QueryClient gives access to the shared react-query caches.
  const queryClient = useQueryClient();

  useEffect(() => {
    // Skip setup entirely when the page is disabled or has no document id.
    if (!enabled || !id) return;

    // Flags/timers guarded on teardown so late callbacks become no-ops.
    let disposed = false;
    let eventSource: EventSource | null = null;
    let pollTimer: number | undefined;

    // Apply an SSE progress event's fields onto the cached document for id.
    const patch = (status: Document["status"], stage: Document["stage"], progress: number, message: string) => {
      // Read the current cached copy; nothing to patch if it is not cached.
      const doc = queryClient.getQueryData<Document>(documentKey(id));
      if (!doc) return;
      // Merge the live fields in, keeping the old error unless freshly failed.
      patchDocumentCaches(queryClient, {
        ...doc,
        status,
        stage,
        progress,
        error: status === "failed" ? message : doc.error,
      });
    };

    // On terminal status, refetch list + detail queries to sync final state.
    const onTerminal = () => {
      queryClient.invalidateQueries({ queryKey: documentsKey });
      queryClient.invalidateQueries({ queryKey: documentKey(id) });
    };

    // Idempotent teardown: close SSE and clear the polling interval.
    const stop = () => {
      if (eventSource) {
        eventSource.close();
        eventSource = null;
      }
      if (pollTimer !== undefined) {
        window.clearInterval(pollTimer);
        pollTimer = undefined;
      }
    };

    // Fallback mode: repeatedly GET the document until it reaches a terminal state.
    const startPolling = () => {
      // A pending teardown should win over starting the fallback.
      if (disposed) return;
      // Ensure only one transport (SSE or polling) is active at a time.
      stop();

      // Individual poll: fetch the doc, patch caches, stop when terminal.
      const poll = async () => {
        if (disposed) return;
        try {
          const doc = await getDocument(id);
          patchDocumentCaches(queryClient, doc);
          if (TERMINAL.has(doc.status)) {
            onTerminal();
            stop();
          }
        } catch {
          // transient; keep polling
        }
      };

      // Fire one poll immediately so progress isn't delayed a full interval.
      void poll();
      // Then keep polling every POLL_MS until stopped.
      pollTimer = window.setInterval(poll, POLL_MS);
    };

    // Create the SSE connection; constructor can throw for invalid URLs.
    try {
      eventSource = new EventSource(eventsUrl(id));
    } catch {
      // Constructor failure: skip SSE entirely and go straight to polling.
      startPolling();
      return () => {
        disposed = true;
        stop();
      };
    }

    // Named-event handler: parse the JSON payload and apply it as progress.
    const handleNamed = (e: MessageEvent) => {
      if (disposed) return;
      let data: SseEvent;
      try {
        data = JSON.parse(e.data) as SseEvent;
      } catch {
        // Malformed payload; ignore this event and wait for the next.
        return;
      }
      patch(data.status, data.stage, data.progress, data.message);
      // A done/failed event ends the stream; close and refetch.
      if (TERMINAL.has(data.status)) {
        onTerminal();
        stop();
      }
    };

    // Register listeners for the named progress/done/failed event types.
    eventSource.addEventListener("progress", handleNamed);
    eventSource.addEventListener("done", handleNamed);
    eventSource.addEventListener("failed", handleNamed);

    // Any transport error (e.g. dropped connection) triggers the poll fallback.
    eventSource.onerror = () => {
      if (disposed) return;
      startPolling();
    };

    // Cleanup on unmount or when id/enabled/queryClient change.
    return () => {
      disposed = true;
      stop();
    };
  }, [id, enabled, queryClient]);
}