/** App config endpoint (accepted formats + size limit). */

import { apiRequest } from "./client";
import type { AppConfig } from "./types";

export function fetchConfig(): Promise<AppConfig> {
  return apiRequest<AppConfig>("/api/config/");
}