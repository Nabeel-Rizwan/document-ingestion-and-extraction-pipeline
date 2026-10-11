// DocumentStatus type enumerating processing lifecycle states.
import type { DocumentStatus } from "../api/types";

// Map each status value to its display label.
const LABELS: Record<DocumentStatus, string> = {
  queued: "Queued",
  processing: "Processing",
  done: "Done",
  failed: "Failed",
};

// Badge showing a document's processing status.
export function StatusBadge({ status }: { status: DocumentStatus }) {
  return (
    <span className={`badge badge--${status}`} data-testid="status-badge">
      {/* Status label text. */}
      {LABELS[status]}
    </span>
  );
}
