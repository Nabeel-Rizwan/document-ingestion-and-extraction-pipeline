/** Document endpoints. */

import { ApiError, apiRequest, toApiError } from "./client";
import type {
  ContentFormat,
  ContentResponse,
  Document,
  ListResponse,
  UploadResponse,
} from "./types";

export function listDocuments(params?: { status?: string; page?: number }): Promise<ListResponse> {
  const search = new URLSearchParams();
  if (params?.status) search.set("status", params.status);
  if (params?.page && params.page > 1) search.set("page", String(params.page));
  const qs = search.toString();
  return apiRequest<ListResponse>(`/api/documents/${qs ? `?${qs}` : ""}`);
}

export function getDocument(id: string): Promise<Document> {
  return apiRequest<Document>(`/api/documents/${id}/`);
}

/**
 * Upload a file via XHR so we can report byte-level progress (fetch cannot).
 * ``onProgress`` receives a 0..1 fraction of the request body sent.
 */
export function uploadDocument(
  file: File,
  onProgress?: (fraction: number) => void,
): Promise<UploadResponse> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/documents/");

    xhr.upload.onprogress = (event) => {
      if (onProgress && event.lengthComputable && event.total > 0) {
        onProgress(event.loaded / event.total);
      }
    };

    xhr.onload = () => {
      const contentType = xhr.getResponseHeader("content-type") || "";
      let body: unknown = xhr.responseText;
      if (contentType.includes("application/json")) {
        try {
          body = JSON.parse(xhr.responseText);
        } catch {
          body = xhr.responseText;
        }
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body as UploadResponse);
      } else {
        reject(toApiError(xhr.status, body));
      }
    };

    xhr.onerror = () => reject(new ApiError(0, "network", "Network error; please try again."));
    xhr.onabort = () => reject(new ApiError(0, "aborted", "Upload was cancelled."));

    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}

export function deleteDocument(id: string): Promise<void> {
  return apiRequest<void>(`/api/documents/${id}/`, { method: "DELETE" });
}

export function contentUrl(
  id: string,
  fmt: ContentFormat,
  opts?: { page?: number; download?: boolean },
): string {
  const search = new URLSearchParams({ format: fmt });
  if (opts?.page !== undefined) search.set("page", String(opts.page));
  if (opts?.download) search.set("download", "1");
  return `/api/documents/${id}/content/?${search.toString()}`;
}

export function getContent(
  id: string,
  fmt: ContentFormat,
  page?: number,
): Promise<ContentResponse | string> {
  return apiRequest<ContentResponse | string>(contentUrl(id, fmt, { page }));
}

export function downloadUrl(id: string): string {
  return `/api/documents/${id}/download/`;
}

export function eventsUrl(id: string): string {
  return `/api/documents/${id}/events/`;
}