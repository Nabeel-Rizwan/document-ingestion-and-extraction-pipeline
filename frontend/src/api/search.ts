/** Search endpoint. */

import { apiRequest } from "./client";
import type { SearchResponse } from "./types";

// Query the fulltext-search endpoint with a limit on the number of results.
export function searchDocuments(query: string, limit = 20): Promise<SearchResponse> {
  // Set the search terms and result cap; limit defaults to 20 result rows.
  const search = new URLSearchParams({ q: query, limit: String(limit) });
  return apiRequest<SearchResponse>(`/api/search/?${search.toString()}`);
}