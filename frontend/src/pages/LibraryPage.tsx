// React hook for local state.
import { useState } from "react";
// React Query hook for the search request.
import { useQuery } from "@tanstack/react-query";
// API function to search documents.
import { searchDocuments } from "../api/search";
// Types describing documents and search responses.
import type { Document, SearchResponse } from "../api/types";
// Child components used on the library page.
import { DocumentTable } from "../components/DocumentTable";
import { EmptyState } from "../components/EmptyState";
import { ProgressBar } from "../components/ProgressBar";
import { SearchBox } from "../components/SearchBox";
import { StatusBadge } from "../components/StatusBadge";
import { SearchResults } from "../components/SearchResults";
import { UploadDropzone } from "../components/UploadDropzone";
// Hooks for app config, live events, documents, and the upload queue.
import { useAppConfig } from "../hooks/useAppConfig";
import { useDocumentEvents } from "../hooks/useDocumentEvents";
import { useDocuments } from "../hooks/useDocuments";
import { useUploadQueue } from "../hooks/useUploadQueue";
// Typed API error for distinguishing server errors.
import { ApiError } from "../api/client";
// Router link for navigating to documents.
import { Link } from "react-router-dom";

// Subscribes individual live event hooks only for in-progress documents.
function LiveRowEvents({ documents }: { documents: Document[] }) {
  return (
    <>
      {/* Render an event subscriber for each non-terminal document. */}
      {documents
        .filter((d) => d.status === "queued" || d.status === "processing")
        .map((d) => (
          <LiveEvents key={d.id} doc={d} />
        ))}
    </>
  );
}

// Headless component that subscribes to a single document's live events.
function LiveEvents({ doc }: { doc: Document }) {
  // Subscribe while the document is not in a terminal state.
  useDocumentEvents(doc.id, doc.status !== "done" && doc.status !== "failed");
  return null;
}

// Small card showing a labeled numeric statistic with an optional tone.
function StatCard({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className={`stat-card${tone ? ` stat-card--${tone}` : ""}`} data-testid="stat-card">
      <span className="stat-card__value">{value}</span>
      <span className="stat-card__label">{label}</span>
    </div>
  );
}

// Renders the upload queue with per-item upload and processing status.
function UploadStatus({
  queue,
  documents,
}: {
  queue: ReturnType<typeof useUploadQueue>;
  documents: Document[];
}) {
  // Destructure the queue API into its items and mutations.
  const { items, remove, clear } = queue;
  // Render nothing when the queue is empty.
  if (items.length === 0) return null;
  // Index the latest documents by id for status lookup.
  const byId = new Map(documents.map((d) => [d.id, d]));

  return (
    <section className="upload-queue card" data-testid="upload-queue">
      <div className="upload-queue__head">
        <h2>Uploads</h2>
        {/* Remove every item from the queue. */}
        <button className="btn btn--ghost btn--sm" onClick={clear}>
          Clear all
        </button>
      </div>
      <ul>
        {/* Render one row per queued upload. */}
        {items.map((item) => {
          // Latest server-side document for this upload, when available.
          const live = item.document ? byId.get(item.document.id) : undefined;
          return (
            <li key={item.id} className="upload-item">
              <div className="upload-item__head">
                <span className="upload-item__name">{item.file.name}</span>
                {/* Show upload progress percentage while uploading. */}
                {item.state === "uploading" && (
                  <span className="badge badge--processing">
                    Uploading {Math.round(item.progress * 100)}%
                  </span>
                )}
                {/* Show "Accepted" once uploaded and before processing starts. */}
                {item.state === "accepted" && !live && <span className="badge badge--done">Accepted</span>}
                {/* Show a duplicate indicator for already-uploaded files. */}
                {item.state === "duplicate" && <span className="badge badge--duplicate">Already uploaded</span>}
                {/* Show the rejection reason for invalid files. */}
                {item.state === "rejected" && (
                  <span className="badge badge--failed" title={item.error}>
                    Rejected: {item.error}
                  </span>
                )}
                {/* Allow dismissing any item that is no longer uploading. */}
                {item.state !== "uploading" && (
                  <button className="btn btn--ghost btn--sm" onClick={() => remove(item.id)}>
                    Dismiss
                  </button>
                )}
              </div>

              {/* Progress bar for the in-flight upload. */}
              {item.state === "uploading" && (
                <ProgressBar
                  progress={item.progress}
                  label={`${item.file.name} upload progress`}
                />
              )}

              {/* Show processing status once the upload is accepted. */}
              {item.state === "accepted" && live && (
                <div className="upload-item__progress">
                  <StatusBadge status={live.status} />
                  {live.status === "done" ? (
                    <Link to={`/documents/${live.id}`} className="document-table__link">
                      View extracted content
                    </Link>
                  ) : live.status === "failed" ? (
                    <span className="error-text">{live.error_code || "Processing failed"}</span>
                  ) : (
                    <>
                      {/* Progress and stage while processing. */}
                      <ProgressBar
                        progress={live.progress}
                        label={`${live.filename} processing progress`}
                      />
                      <span className="stage-message">{live.stage}</span>
                    </>
                  )}
                </div>
              )}

              {/* Link to the existing document for duplicates. */}
              {item.state === "duplicate" && item.document && (
                <Link to={`/documents/${item.document.id}`} className="document-table__link">
                  View existing document
                </Link>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

// Main library page: uploads, stats, search, and the document list.
export function LibraryPage() {
  // Server-provided configuration (supported formats, limits).
  const config = useAppConfig();
  // Current search query string.
  const [searchQuery, setSearchQuery] = useState("");
  // Upload queue state and actions.
  const uploadQueue = useUploadQueue();

  // Query the document list with adaptive polling while work is in progress.
  const docsQuery = useDocuments(undefined, {
    refetchInterval: (query) => {
      // Current results from the query.
      const results = query.state.data?.results ?? [];
      // Whether any document is still being processed.
      const anyNonTerminal = results.some(
        (d) => d.status !== "done" && d.status !== "failed",
      );
      // Poll every 5s while documents are processing or uploads are in flight.
      return anyNonTerminal || uploadQueue.items.some((i) => i.state === "uploading") ? 5000 : false;
    },
  });

  // Query for search results, enabled only for queries of 2+ characters.
  const searchQueryData = useQuery<SearchResponse>({
    queryKey: ["search", searchQuery],
    queryFn: () => searchDocuments(searchQuery),
    enabled: searchQuery.trim().length >= 2,
  });

  // Alias for the document list query.
  const listQuery = docsQuery;
  // Documents returned by the list query.
  const documents = listQuery.data?.results ?? [];
  // Aggregate total/active/done/failed counts across documents.
  const counts = documents.reduce(
    (acc, d) => {
      // Count every document in the total.
      acc.total += 1;
      // Track completed, failed, or active states.
      if (d.status === "done") acc.done += 1;
      else if (d.status === "failed") acc.failed += 1;
      else acc.active += 1;
      return acc;
    },
    { total: 0, active: 0, done: 0, failed: 0 },
  );

  // Whether a search is currently active.
  const searching = searchQuery.trim().length >= 2;

  return (
    <div className="page library-page">
      <header className="page-header page-header--split">
        <div>
          <h1>Documents</h1>
          <p className="subtitle">
            Upload PDF and DOCX files; the pipeline routes each page, extracts content and
            indexes it for search.
          </p>
        </div>
      </header>

      {/* Dropzone that enqueues accepted files into the upload queue. */}
      <UploadDropzone config={config.data} onFiles={(files) => uploadQueue.addFiles(files)} />
      {/* Upload queue status panel. */}
      <UploadStatus queue={uploadQueue} documents={documents} />

      {/* Summary stat cards, hidden while searching. */}
      {!searching && documents.length > 0 && (
        <div className="stat-grid">
          <StatCard label="Documents" value={counts.total} />
          <StatCard label="Processing" value={counts.active} tone="active" />
          <StatCard label="Completed" value={counts.done} tone="done" />
          <StatCard label="Failed" value={counts.failed} tone="failed" />
        </div>
      )}

      {/* Search input that updates the query state. */}
      <SearchBox onSearch={(q) => setSearchQuery(q)} />

      {/* Render search results or the document list depending on state. */}
      {searching ? (
        searchQueryData.isLoading ? (
          <p className="muted">Searching…</p>
        ) : searchQueryData.isError ? (
          <p className="error-text">
            {/* Show the API error message when available. */}
            {searchQueryData.error instanceof ApiError
              ? searchQueryData.error.message
              : "Search failed."}
          </p>
        ) : (
          <SearchResults data={searchQueryData.data} />
        )
      ) : (
        <>
          {/* Subscribe to live events for in-progress documents. */}
          <LiveRowEvents documents={documents} />
          {listQuery.isLoading ? (
            <div className="skeleton-list">
              <div className="skeleton skeleton--block" />
              <div className="skeleton skeleton--block" />
              <div className="skeleton skeleton--block" />
            </div>
          ) : listQuery.isError ? (
            <p className="error-text">
              {/* Show the API error message when available. */}
              {listQuery.error instanceof ApiError
                ? listQuery.error.message
                : "Failed to load documents."}{" "}
              {/* Retry the document list query. */}
              <button className="btn btn--sm" onClick={() => void listQuery.refetch()}>
                Retry
              </button>
            </p>
          ) : documents.length === 0 ? (
            <EmptyState
              title="No documents yet"
              hint="Upload a PDF or DOCX to get started."
            />
          ) : (
            <DocumentTable documents={documents} />
          )}
        </>
      )}
    </div>
  );
}