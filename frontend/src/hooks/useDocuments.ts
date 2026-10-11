/** Document queries. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { deleteDocument, getDocument, listDocuments, uploadDocument } from "../api/documents";
import type { Document } from "../api/types";

// React-query cache key for every list of documents (with its params suffix).
export const documentsKey = ["documents"] as const;
// Cache key factory for a single document's detail query.
export const documentKey = (id: string) => ["document", id] as const;

// Hook: pageable, optionally status-filtered list of documents.
export function useDocuments(
  params?: { status?: string; page?: number },
  // Polling can be a fixed interval or a callback computing it per query state.
  options?: { refetchInterval?: number | ((query: { state: { data?: { results?: Document[] } } }) => number | false) },
) {
  return useQuery({
    // Include params in the key so different filters/pages are cached separately.
    queryKey: [...documentsKey, params],
    queryFn: () => listDocuments(params),
    // Only attach refetchInterval when provided; keeps the query config tidy.
    ...(options?.refetchInterval !== undefined ? { refetchInterval: options.refetchInterval } : {}),
  });
}

// Hook: a single document's detail query, disabled until an id exists.
export function useDocument(id: string) {
  return useQuery({
    queryKey: documentKey(id),
    queryFn: () => getDocument(id),
    // Skip the request while id is empty (e.g. '' on initial render).
    enabled: !!id,
  });
}

// Hook: upload a single file and keep list/detail caches consistent.
export function useUpload() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => uploadDocument(file),
    onSuccess: (result) => {
      // The list may now contain a new row; force a refetch.
      queryClient.invalidateQueries({ queryKey: documentsKey });
      // Pre-seed the detail cache so a click-through renders instantly.
      queryClient.setQueryData(documentKey(result.document.id), result.document);
    },
  });
}

// Hook: delete a document and evict it from every cache.
export function useDeleteDocument() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteDocument,
    onSuccess: (_data, id) => {
      // Remove the deleted document's cached detail entirely.
      queryClient.removeQueries({ queryKey: documentKey(id) });
      // The list contents changed; refetch rather than trust the stale copy.
      queryClient.invalidateQueries({ queryKey: documentsKey });
    },
  });
}

/** Patch a single document inside both the list and single-query caches. */
export function patchDocumentCaches(
  queryClient: ReturnType<typeof useQueryClient>,
  doc: Document,
): void {
  // Merge into the detail cache, keeping any older cached fields not in `doc`.
  queryClient.setQueryData<Document>(documentKey(doc.id), (current) =>
    current ? { ...current, ...doc } : doc,
  );
  // Merge into the results array of every list query under the documents key.
  queryClient.setQueriesData<{ results: Document[] }>(
    { queryKey: documentsKey },
    (current) => {
      // Leave other query shapes (e.g. no results array) untouched.
      if (!current) return current;
      return {
        ...current,
        // Replace only the matching row; other cached documents are preserved.
        results: current.results.map((d) => (d.id === doc.id ? { ...d, ...doc } : d)),
      };
    },
  );
}