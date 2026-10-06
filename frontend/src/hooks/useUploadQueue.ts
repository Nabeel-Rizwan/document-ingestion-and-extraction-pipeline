/** Concurrent upload queue with per-file states.

At most 3 concurrent uploads, one POST per file. Per-file states:
uploading -> accepted | duplicate ("already uploaded") | rejected.
 */

import { useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";
import { uploadDocument } from "../api/documents";
import type { Document } from "../api/types";

const MAX_CONCURRENT = 3;

export type UploadState = "uploading" | "accepted" | "duplicate" | "rejected";

export interface UploadItem {
  id: string;
  file: File;
  state: UploadState;
  document?: Document;
  error?: string;
}

export function useUploadQueue() {
  const [items, setItems] = useState<UploadItem[]>([]);
  const startedRef = useRef<Set<string>>(new Set());

  const addFiles = (files: File[]) => {
    const next: UploadItem[] = files.map((file) => ({
      id: crypto.randomUUID(),
      file,
      state: "uploading",
    }));
    setItems((prev) => [...prev, ...next]);
  };

  const remove = (id: string) => {
    startedRef.current.delete(id);
    setItems((prev) => prev.filter((i) => i.id !== id));
  };

  const clear = () => {
    startedRef.current.clear();
    setItems([]);
  };

  useEffect(() => {
    const uploading = items.filter((i) => i.state === "uploading");
    const active = uploading.filter((i) => startedRef.current.has(i.id)).length;
    const pending = uploading.filter((i) => !startedRef.current.has(i.id));
    const slots = Math.max(0, MAX_CONCURRENT - active);
    const toStart = pending.slice(0, slots);

    for (const item of toStart) {
      startedRef.current.add(item.id);
      void (async () => {
        try {
          const result = await uploadDocument(item.file);
          setItems((prev) =>
            prev.map((i) =>
              i.id === item.id
                ? {
                    ...i,
                    state: result.duplicate ? "duplicate" : "accepted",
                    document: result.document,
                  }
                : i,
            ),
          );
        } catch (err) {
          const message = err instanceof ApiError ? err.message : "Upload failed.";
          setItems((prev) =>
            prev.map((i) => (i.id === item.id ? { ...i, state: "rejected", error: message } : i)),
          );
        } finally {
          startedRef.current.delete(item.id);
        }
      })();
    }
  }, [items]);

  return { items, addFiles, remove, clear };
}