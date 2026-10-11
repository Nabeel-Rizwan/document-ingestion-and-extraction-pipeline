/** Concurrent upload queue with per-file progress and states.

At most 3 concurrent uploads, one POST per file. Each item tracks:
  uploading (with 0..1 byte progress) -> accepted | duplicate | rejected.
On acceptance the documents list is invalidated so the new row appears and its
processing progress starts updating live.
 */

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../api/client";
import { uploadDocument } from "../api/documents";
import type { Document } from "../api/types";
import { documentsKey } from "./useDocuments";

// Cap on how many uploads may run simultaneously.
const MAX_CONCURRENT = 3;

// Lifecycle of a queued file: uploading until it resolves to one of the rest.
export type UploadState = "uploading" | "accepted" | "duplicate" | "rejected";

// One entry in the queue: the file plus its live state/progress/result.
export interface UploadItem {
  id: string;
  file: File;
  state: UploadState;
  // 0..1 byte-level transfer progress while uploading.
  progress: number;
  document?: Document;
  error?: string;
}

// Monotonic counter used only in the randomUUID fallback path.
let counter = 0;
function itemId(): string {
  counter += 1;
  // Prefer a cryptographically random UUID when available (unique across tabs).
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  // Fallback: timestamp + counter, unique enough within this session.
  return `upload-${Date.now()}-${counter}`;
}

export function useUploadQueue() {
  // The visible queue of files being added/uploaded.
  const [items, setItems] = useState<UploadItem[]>([]);
  // Set of item ids whose upload has already been started this effect run.
  const startedRef = useRef<Set<string>>(new Set());
  const queryClient = useQueryClient();

  // Add new files to the queue with initial uploading/0 progress state.
  const addFiles = (files: File[]) => {
    const next: UploadItem[] = files.map((file) => ({
      id: itemId(),
      file,
      state: "uploading",
      progress: 0,
    }));
    // Append them to whatever items are already queued.
    setItems((prev) => [...prev, ...next]);
  };

  // Remove one item from the queue (by id), also forgetting its started marker.
  const remove = (id: string) => {
    startedRef.current.delete(id);
    setItems((prev) => prev.filter((i) => i.id !== id));
  };

  // Clear the whole queue, resetting the started-tracking set too.
  const clear = () => {
    startedRef.current.clear();
    setItems([]);
  };

  // Queue pump: whenever the items change, start uploads until we hit the cap.
  useEffect(() => {
    // Only the not-yet-finished files are candidates for starting.
    const uploading = items.filter((i) => i.state === "uploading");
    // Count how many uploads are already in flight (started and still uploading).
    const active = uploading.filter((i) => startedRef.current.has(i.id)).length;
    // Files that haven't been started yet; these are eligible to begin.
    const pending = uploading.filter((i) => !startedRef.current.has(i.id));
    // How many more we may start right now after subtracting active ones.
    const slots = Math.max(0, MAX_CONCURRENT - active);
    // Start only up to the free slots, in queue order.
    const toStart = pending.slice(0, slots);

    // Kick off an upload for each slot we just reserved.
    for (const item of toStart) {
      // Mark started first so re-runs of this effect don't double-start it.
      startedRef.current.add(item.id);
      void (async () => {
        try {
          // Kick off the XHR upload; update progress on the matching item.
          const result = await uploadDocument(item.file, (fraction) => {
            setItems((prev) =>
              prev.map((i) => (i.id === item.id ? { ...i, progress: fraction } : i)),
            );
          });
          // On success, mark the file accepted (or duplicate) at 100%.
          setItems((prev) =>
            prev.map((i) =>
              i.id === item.id
                ? {
                    ...i,
                    progress: 1,
                    // Backend reported this file already existed.
                    state: result.duplicate ? "duplicate" : "accepted",
                    document: result.document,
                  }
                : i,
            ),
          );
          // The library list must refetch so the new row shows up (and starts
          // receiving live processing progress).
          void queryClient.invalidateQueries({ queryKey: documentsKey });
        } catch (err) {
          // Surface ApiError messages; anything else falls back to a generic one.
          const message = err instanceof ApiError ? err.message : "Upload failed.";
          setItems((prev) =>
            prev.map((i) => (i.id === item.id ? { ...i, state: "rejected", error: message } : i)),
          );
        } finally {
          // Free this slot so the effect can start the next pending file.
          startedRef.current.delete(item.id);
        }
      })();
    }
    // Re-run whenever the queue changes or the query client instance changes.
  }, [items, queryClient]);

  // Expose the queue state and the operations to mutate it.
  return { items, addFiles, remove, clear };
}