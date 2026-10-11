/** Document endpoints. */

import { ApiError, apiRequest, toApiError } from "./client";
import type {
  ContentFormat,
  ContentResponse,
  Document,
  ListResponse,
  UploadResponse,
} from "./types";

// Fetch a page of documents, optionally filtered by processing status.
export function listDocuments(params?: { status?: string; page?: number }): Promise<ListResponse> {
  // Build the query string incrementally from the supplied optional filters.
  const search = new URLSearchParams();
  // Backend "status" filter; only set when a status was provided.
  if (params?.status) search.set("status", params.status);
  // Page is omitted when 1 (the default) to keep URLs minimal.
  if (params?.page && params.page > 1) search.set("page", String(params.page));
  const qs = search.toString();
  // Append the query string only when there is at least one parameter.
  return apiRequest<ListResponse>(`/api/documents/${qs ? `?${qs}` : ""}`);
}

// Fetch a single document's metadata by id.
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
  // Wrap the XHR lifecycle in a Promise so callers can await the result.
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    // POST the file to the documents collection endpoint.
    xhr.open("POST", "/api/documents/");

    // Track bytes actually sent; only reportable when Content-Length is known.
    xhr.upload.onprogress = (event) => {
      if (onProgress && event.lengthComputable && event.total > 0) {
        // Progress is the fraction of total bytes uploaded so far.
        onProgress(event.loaded / event.total);
      }
    };

    // The request finished (2xx or error); inspect status and response body.
    xhr.onload = () => {
      const contentType = xhr.getResponseHeader("content-type") || "";
      // Default to the raw text; try to parse JSON when the server says so.
      let body: unknown = xhr.responseText;
      if (contentType.includes("application/json")) {
        try {
          body = JSON.parse(xhr.responseText);
        } catch {
          // Malformed JSON: keep the raw text so the error still shows something.
          body = xhr.responseText;
        }
      }
      // 2xx range means success; resolve with the parsed upload result.
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body as UploadResponse);
      } else {
        // Otherwise convert the status + body into the standard ApiError.
        reject(toApiError(xhr.status, body));
      }
    };

    // Transport-level failure (e.g. offline) and abort both reject the promise.
    xhr.onerror = () => reject(new ApiError(0, "network", "Network error; please try again."));
    xhr.onabort = () => reject(new ApiError(0, "aborted", "Upload was cancelled."));

    // Send the file as a multipart/form-data request under the "file" field.
    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}

// DELETE a document; the void return type reflects the empty success body.
export function deleteDocument(id: string): Promise<void> {
  return apiRequest<void>(`/api/documents/${id}/`, { method: "DELETE" });
}

// Build the content endpoint URL for a format, optional page, and download flag.
export function contentUrl(
  id: string,
  fmt: ContentFormat,
  opts?: { page?: number; download?: boolean },
): string {
  // Always include the requested content format in the query string.
  const search = new URLSearchParams({ format: fmt });
  // Request a specific page when given (rather than the whole document).
  if (opts?.page !== undefined) search.set("page", String(opts.page));
  // A download flag makes the response Content-Disposition attachment.
  if (opts?.download) search.set("download", "1");
  return `/api/documents/${id}/content/?${search.toString()}`;
}

// Fetch document content; returns parsed blocks (JSON) or raw text for other formats.
export function getContent(
  id: string,
  fmt: ContentFormat,
  page?: number,
): Promise<ContentResponse | string> {
  return apiRequest<ContentResponse | string>(contentUrl(id, fmt, { page }));
}

// Build the download (original file) URL for a document id.
export function downloadUrl(id: string): string {
  return `/api/documents/${id}/download/`;
}

// Build the SSE (Server-Sent Events) stream URL for a document id.
export function eventsUrl(id: string): string {
  return `/api/documents/${id}/events/`;
}