/** App config endpoint (accepted formats + size limit). */

import { apiRequest } from "./client";
import type { AppConfig } from "./types";

// Fetch the app-config endpoint and parse the response into the AppConfig shape.
export function fetchConfig(): Promise<AppConfig> {
  return apiRequest<AppConfig>("/api/config/");
}