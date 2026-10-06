import { Link } from "react-router-dom";
import type { Document } from "../api/types";
import { formatBytes, relativeTime } from "../lib/format";
import { MethodBadge } from "./MethodBadge";
import { ProgressBar } from "./ProgressBar";
import { StatusBadge } from "./StatusBadge";

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
          <th />
        </tr>
      </thead>
      <tbody>
        {documents.map((doc) => (
          <tr key={doc.id}>
            <td>
              <Link to={`/documents/${doc.id}`} className="document-table__link">
                {doc.filename}
              </Link>
            </td>
            <td className="mono">{formatBytes(doc.size)}</td>
            <td>
              <StatusBadge status={doc.status} />
            </td>
            <td>
              {doc.status === "done" || doc.status === "failed" ? (
                <span className="progress-final">
                  {doc.status === "done" ? "100%" : doc.error_code || "failed"}
                </span>
              ) : (
                <ProgressBar progress={doc.progress} label={`${doc.filename} progress`} />
              )}
              {doc.status !== "done" && doc.status !== "failed" && doc.stage && (
                <span className="stage-message" aria-live="polite">
                  {doc.stage}
                </span>
              )}
            </td>
            <td>
              <MethodBadge method={doc.method} />
            </td>
            <td className="mono">{relativeTime(doc.created_at)}</td>
            <td>
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