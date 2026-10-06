/** Document endpoints. */

import { apiRequest } from "./client";
import type { ContentResponse, Document, ListResponse, UploadResponse } from "./types";

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

export function uploadDocument(file: File): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);
  return apiRequest<UploadResponse>("/api/documents/", {
    method: "POST",
    body: form,
  });
}

export function deleteDocument(id: string): Promise<void> {
  return apiRequest<void>(`/api/documents/${id}/`, { method: "DELETE" });
}

export function getContent(
  id: string,
  fmt: "json" | "markdown" | "text",
  page?: number,
): Promise<ContentResponse | string> {
  const search = new URLSearchParams({ format: fmt });
  if (page !== undefined) search.set("page", String(page));
  return apiRequest<ContentResponse | string>(`/api/documents/${id}/content/?${search.toString()}`);
}

export function downloadUrl(id: string): string {
  return `/api/documents/${id}/download/`;
}

export function eventsUrl(id: string): string {
  return `/api/documents/${id}/events/`;
}