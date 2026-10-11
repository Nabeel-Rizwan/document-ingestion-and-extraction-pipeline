// Link component for navigating to a document's detail page.
import { Link } from "react-router-dom";
// Document type describing a library row.
import type { Document } from "../api/types";
// Formatting helpers for byte sizes and relative timestamps.
import { formatBytes, relativeTime } from "../lib/format";
// Badge components for method, progress, and status cells.
import { MethodBadge } from "./MethodBadge";
import { ProgressBar } from "./ProgressBar";
import { StatusBadge } from "./StatusBadge";

// Table listing documents with status, progress, and optional delete action.
export function DocumentTable({
  documents,
  onDelete,
}: {
  documents: Document[];
  onDelete?: (id: string) => void;
}) {
  return (
    <table className="document-table" data-testid="document-table">
      <thead>
        <tr>
          <th>Filename</th>
          <th>Size</th>
          <th>Status</th>
          <th>Progress</th>
          <th>Method</th>
          <th>Created</th>
          {/* Empty header cell for the actions column. */}
          <th />
        </tr>
      </thead>
      <tbody>
        {/* Render one row per document. */}
        {documents.map((doc) => (
          <tr key={doc.id}>
            <td>
              {/* Link to the document detail page. */}
              <Link to={`/documents/${doc.id}`} className="document-table__link">
                {doc.filename}
              </Link>
            </td>
            {/* Human-readable file size in monospace. */}
            <td className="mono">{formatBytes(doc.size)}</td>
            <td>
              {/* Colored status badge. */}
              <StatusBadge status={doc.status} />
            </td>
            <td>
              {/* Show final state text for completed/failed, else a progress bar. */}
              {doc.status === "done" || doc.status === "failed" ? (
                <span className="progress-final">
                  {doc.status === "done" ? "100%" : doc.error_code || "failed"}
                </span>
              ) : (
                <ProgressBar progress={doc.progress} label={`${doc.filename} progress`} />
              )}
              {/* Show the current stage while still processing. */}
              {doc.status !== "done" && doc.status !== "failed" && doc.stage && (
                <span className="stage-message" aria-live="polite">
                  {doc.stage}
                </span>
              )}
            </td>
            <td>
              {/* Badge describing the extraction method. */}
              <MethodBadge method={doc.method} />
            </td>
            {/* Relative creation time in monospace. */}
            <td className="mono">{relativeTime(doc.created_at)}</td>
            <td>
              {/* Render a delete button only when a handler is provided. */}
              {onDelete && (
                <button
                  className="btn btn--danger btn--sm"
                  onClick={() => onDelete(doc.id)}
                  aria-label={`Delete ${doc.filename}`}
                >
                  Delete
                </button>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
