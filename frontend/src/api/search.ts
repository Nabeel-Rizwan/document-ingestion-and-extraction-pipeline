/** Search endpoint. */

import { apiRequest } from "./client";
import type { SearchResponse } from "./types";

export function searchDocuments(query: string, limit = 20): Promise<SearchResponse> {
  const search = new URLSearchParams({ q: query, limit: String(limit) });
  return apiRequest<SearchResponse>(`/api/search/?${search.toString()}`);
}