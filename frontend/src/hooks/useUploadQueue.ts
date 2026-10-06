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

const MAX_CONCURRENT = 3;

export type UploadState = "uploading" | "accepted" | "duplicate" | "rejected";

export interface UploadItem {
  id: string;
  file: File;
  state: UploadState;
  progress: number;
  document?: Document;
  error?: string;
}

let counter = 0;
function itemId(): string {
  counter += 1;
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `upload-${Date.now()}-${counter}`;
}

export function useUploadQueue() {
  const [items, setItems] = useState<UploadItem[]>([]);
  const startedRef = useRef<Set<string>>(new Set());
  const queryClient = useQueryClient();

  const addFiles = (files: File[]) => {
    const next: UploadItem[] = files.map((file) => ({
      id: itemId(),
      file,
      state: "uploading",
      progress: 0,
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
          const result = await uploadDocument(item.file, (fraction) => {
            setItems((prev) =>
              prev.map((i) => (i.id === item.id ? { ...i, progress: fraction } : i)),
            );
          });
          setItems((prev) =>
            prev.map((i) =>
              i.id === item.id
                ? {
                    ...i,
                    progress: 1,
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
          const message = err instanceof ApiError ? err.message : "Upload failed.";
          setItems((prev) =>
            prev.map((i) => (i.id === item.id ? { ...i, state: "rejected", error: message } : i)),
          );
        } finally {
          startedRef.current.delete(item.id);
        }
      })();
    }
  }, [items, queryClient]);

  return { items, addFiles, remove, clear };
}
