/** App config query. */

import { useQuery } from "@tanstack/react-query";
import { fetchConfig } from "../api/config";
import type { AppConfig } from "../api/types";

export function useAppConfig() {
  return useQuery<AppConfig>({
    queryKey: ["config"],
    queryFn: fetchConfig,
    staleTime: Infinity,
  });
}