// Type for arbitrary React children passed as an action element.
import type { ReactNode } from "react";

// Centered placeholder shown when there is no content to display.
export function EmptyState({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="empty-state">
      {/* Primary empty-state message. */}
      <h3>{title}</h3>
      {/* Optional secondary hint. */}
      {hint && <p>{hint}</p>}
      {/* Optional action element (e.g. a button). */}
      {action}
    </div>
  );
}
