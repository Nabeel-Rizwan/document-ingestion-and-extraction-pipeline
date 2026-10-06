import type { DocumentStatus } from "../api/types";

const LABELS: Record<DocumentStatus, string> = {
  queued: "Queued",
  processing: "Processing",
  done: "Done",
  failed: "Failed",
};

export function StatusBadge({ status }: { status: DocumentStatus }) {
  return (
    <span className={`badge badge--${status}`} data-testid="status-badge">
      {LABELS[status]}
    </span>
  );
}