/** App config query. */

import { useQuery } from "@tanstack/react-query";
import { fetchConfig } from "../api/config";
import type { AppConfig } from "../api/types";

// React-query hook that fetches the app config once and caches it forever.
export function useAppConfig() {
  return useQuery<AppConfig>({
    // Single fixed key: there is exactly one config source.
    queryKey: ["config"],
    queryFn: fetchConfig,
    // Config never changes at runtime, so never refetch or expire it.
    staleTime: Infinity,
  });
}