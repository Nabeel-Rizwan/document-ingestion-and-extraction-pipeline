/** Formatting helpers. */

// Render a byte count as a human-friendly string with the right unit.
export function formatBytes(bytes: number): string {
  // Zero is a special case: no unit division needed.
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  // Which unit bucket the byte count falls into (log base 1024).
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  // Scale the raw bytes down into the chosen unit's magnitude.
  const value = bytes / Math.pow(1024, i);
  // Show decimals only for smaller values; whole numbers for KB+ or bytes.
  return `${value.toFixed(value >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
}

// Human-friendly "time ago" label for an ISO 8601 timestamp.
export function relativeTime(iso: string): string {
  // Convert the ISO string to a millisecond epoch value.
  const then = new Date(iso).getTime();
  // Invalid dates yield NaN; report them as unknown rather than garbage.
  if (Number.isNaN(then)) return "unknown";
  // Age in milliseconds between now and the given timestamp.
  const diff = Date.now() - then;
  const seconds = Math.round(diff / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  // Older than ~30 days: fall back to the locale-formatted calendar date.
  return new Date(iso).toLocaleDateString();
}