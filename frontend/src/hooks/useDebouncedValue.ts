/** Debounced value hook. */

import { useEffect, useState } from "react";

// Return `value` only after it has been unchanged for `delayMs`, so rapidly
// changing input (e.g. keystrokes) does not trigger work on every update.
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  // Holds the last value that "settled"; starts as the initial value.
  const [debounced, setDebounced] = useState(value);

  // Re-arm a one-shot timer whenever the source value (or delay) changes.
  useEffect(() => {
    // If the value stops changing for delayMs, commit it as debounced.
    const id = window.setTimeout(() => setDebounced(value), delayMs);
    // Cancel the pending timer on cleanup, e.g. on unmount or re-run.
    return () => window.clearTimeout(id);
  }, [value, delayMs]);

  // Consumers read the settled (debounced) value.
  return debounced;
}