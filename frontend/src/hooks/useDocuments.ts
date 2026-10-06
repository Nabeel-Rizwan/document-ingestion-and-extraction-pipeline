/** Document queries. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { deleteDocument, getDocument, listDocuments, uploadDocument } from "../api/documents";
import type { Document } from "../api/types";

export const documentsKey = ["documents"] as const;
export const documentKey = (id: string) => ["document", id] as const;

export function useDocuments(
  params?: { status?: string; page?: number },
  options?: { refetchInterval?: number | ((query: { state: { data?: { results?: Document[] } } }) => number | false) },
) {
  return useQuery({
    queryKey: [...documentsKey, params],
    queryFn: () => listDocuments(params),
    ...(options?.refetchInterval !== undefined ? { refetchInterval: options.refetchInterval } : {}),
  });
}

export function useDocument(id: string) {
  return useQuery({
    queryKey: documentKey(id),
    queryFn: () => getDocument(id),
    enabled: !!id,
  });
}

export function useUpload() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: uploadDocument,
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: documentsKey });
      queryClient.setQueryData(documentKey(result.document.id), result.document);
    },
  });
}

export function useDeleteDocument() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteDocument,
    onSuccess: (_data, id) => {
      queryClient.removeQueries({ queryKey: documentKey(id) });
      queryClient.invalidateQueries({ queryKey: documentsKey });
    },
  });
}

/** Patch a single document inside both the list and single-query caches. */
export function patchDocumentCaches(
  queryClient: ReturnType<typeof useQueryClient>,
  doc: Document,
): void {
  queryClient.setQueryData<Document>(documentKey(doc.id), (current) =>
    current ? { ...current, ...doc } : doc,
  );
  queryClient.setQueriesData<{ results: Document[] }>(
    { queryKey: documentsKey },
    (current) => {
      if (!current) return current;
      return {
        ...current,
        results: current.results.map((d) => (d.id === doc.id ? { ...d, ...doc } : d)),
      };
    },
  );
}