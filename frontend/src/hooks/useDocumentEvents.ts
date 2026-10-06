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

const TERMINAL = new Set(["done", "failed"]);
const POLL_MS = 1500;

export function useDocumentEvents(id: string, enabled: boolean): void {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!enabled || !id) return;

    let disposed = false;
    let eventSource: EventSource | null = null;
    let pollTimer: number | undefined;

    const patch = (status: Document["status"], stage: Document["stage"], progress: number, message: string) => {
      const doc = queryClient.getQueryData<Document>(documentKey(id));
      if (!doc) return;
      patchDocumentCaches(queryClient, {
        ...doc,
        status,
        stage,
        progress,
        error: status === "failed" ? message : doc.error,
      });
    };

    const onTerminal = () => {
      queryClient.invalidateQueries({ queryKey: documentsKey });
      queryClient.invalidateQueries({ queryKey: documentKey(id) });
    };

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

    const startPolling = () => {
      if (disposed) return;
      stop();

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

      void poll();
      pollTimer = window.setInterval(poll, POLL_MS);
    };

    try {
      eventSource = new EventSource(eventsUrl(id));
    } catch {
      startPolling();
      return () => {
        disposed = true;
        stop();
      };
    }

    const handleNamed = (e: MessageEvent) => {
      if (disposed) return;
      let data: SseEvent;
      try {
        data = JSON.parse(e.data) as SseEvent;
      } catch {
        return;
      }
      patch(data.status, data.stage, data.progress, data.message);
      if (TERMINAL.has(data.status)) {
        onTerminal();
        stop();
      }
    };

    eventSource.addEventListener("progress", handleNamed);
    eventSource.addEventListener("done", handleNamed);
    eventSource.addEventListener("failed", handleNamed);

    eventSource.onerror = () => {
      if (disposed) return;
      startPolling();
    };

    return () => {
      disposed = true;
      stop();
    };
  }, [id, enabled, queryClient]);
}