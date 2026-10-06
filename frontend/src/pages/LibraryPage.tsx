import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { searchDocuments } from "../api/search";
import type { Document, SearchResponse } from "../api/types";
import { DocumentTable } from "../components/DocumentTable";
import { EmptyState } from "../components/EmptyState";
import { ProgressBar } from "../components/ProgressBar";
import { SearchBox } from "../components/SearchBox";
import { StatusBadge } from "../components/StatusBadge";
import { SearchResults } from "../components/SearchResults";
import { UploadDropzone } from "../components/UploadDropzone";
import { useAppConfig } from "../hooks/useAppConfig";
import { useDocumentEvents } from "../hooks/useDocumentEvents";
import { useDocuments } from "../hooks/useDocuments";
import { useUploadQueue } from "../hooks/useUploadQueue";
import { ApiError } from "../api/client";
import { Link } from "react-router-dom";

function LiveRowEvents({ documents }: { documents: Document[] }) {
  return (
    <>
      {documents
        .filter((d) => d.status === "queued" || d.status === "processing")
        .map((d) => (
          <LiveEvents key={d.id} doc={d} />
        ))}
    </>
  );
}

function LiveEvents({ doc }: { doc: Document }) {
  useDocumentEvents(doc.id, doc.status !== "done" && doc.status !== "failed");
  return null;
}

function StatCard({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className={`stat-card${tone ? ` stat-card--${tone}` : ""}`} data-testid="stat-card">
      <span className="stat-card__value">{value}</span>
      <span className="stat-card__label">{label}</span>
    </div>
  );
}

function UploadStatus({
  queue,
  documents,
}: {
  queue: ReturnType<typeof useUploadQueue>;
  documents: Document[];
}) {
  const { items, remove, clear } = queue;
  if (items.length === 0) return null;
  const byId = new Map(documents.map((d) => [d.id, d]));

  return (
    <section className="upload-queue card" data-testid="upload-queue">
      <div className="upload-queue__head">
        <h2>Uploads</h2>
        <button className="btn btn--ghost btn--sm" onClick={clear}>
          Clear all
        </button>
      </div>
      <ul>
        {items.map((item) => {
          const live = item.document ? byId.get(item.document.id) : undefined;
          return (
            <li key={item.id} className="upload-item">
              <div className="upload-item__head">
                <span className="upload-item__name">{item.file.name}</span>
                {item.state === "uploading" && (
                  <span className="badge badge--processing">
                    Uploading {Math.round(item.progress * 100)}%
                  </span>
                )}
                {item.state === "accepted" && !live && <span className="badge badge--done">Accepted</span>}
                {item.state === "duplicate" && <span className="badge badge--duplicate">Already uploaded</span>}
                {item.state === "rejected" && (
                  <span className="badge badge--failed" title={item.error}>
                    Rejected: {item.error}
                  </span>
                )}
                {item.state !== "uploading" && (
                  <button className="btn btn--ghost btn--sm" onClick={() => remove(item.id)}>
                    Dismiss
                  </button>
                )}
              </div>

              {item.state === "uploading" && (
                <ProgressBar
                  progress={item.progress}
                  label={`${item.file.name} upload progress`}
                />
              )}

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
                      <ProgressBar
                        progress={live.progress}
                        label={`${live.filename} processing progress`}
                      />
                      <span className="stage-message">{live.stage}</span>
                    </>
                  )}
                </div>
              )}

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

export function LibraryPage() {
  const config = useAppConfig();
  const [searchQuery, setSearchQuery] = useState("");
  const uploadQueue = useUploadQueue();

  const docsQuery = useDocuments(undefined, {
    refetchInterval: (query) => {
      const results = query.state.data?.results ?? [];
      const anyNonTerminal = results.some(
        (d) => d.status !== "done" && d.status !== "failed",
      );
      return anyNonTerminal || uploadQueue.items.some((i) => i.state === "uploading") ? 5000 : false;
    },
  });

  const searchQueryData = useQuery<SearchResponse>({
    queryKey: ["search", searchQuery],
    queryFn: () => searchDocuments(searchQuery),
    enabled: searchQuery.trim().length >= 2,
  });

  const listQuery = docsQuery;
  const documents = listQuery.data?.results ?? [];
  const counts = documents.reduce(
    (acc, d) => {
      acc.total += 1;
      if (d.status === "done") acc.done += 1;
      else if (d.status === "failed") acc.failed += 1;
      else acc.active += 1;
      return acc;
    },
    { total: 0, active: 0, done: 0, failed: 0 },
  );

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

      <UploadDropzone config={config.data} onFiles={(files) => uploadQueue.addFiles(files)} />
      <UploadStatus queue={uploadQueue} documents={documents} />

      {!searching && documents.length > 0 && (
        <div className="stat-grid">
          <StatCard label="Documents" value={counts.total} />
          <StatCard label="Processing" value={counts.active} tone="active" />
          <StatCard label="Completed" value={counts.done} tone="done" />
          <StatCard label="Failed" value={counts.failed} tone="failed" />
        </div>
      )}

      <SearchBox onSearch={(q) => setSearchQuery(q)} />

      {searching ? (
        searchQueryData.isLoading ? (
          <p className="muted">Searching…</p>
        ) : searchQueryData.isError ? (
          <p className="error-text">
            {searchQueryData.error instanceof ApiError
              ? searchQueryData.error.message
              : "Search failed."}
          </p>
        ) : (
          <SearchResults data={searchQueryData.data} />
        )
      ) : (
        <>
          <LiveRowEvents documents={documents} />
          {listQuery.isLoading ? (
            <div className="skeleton-list">
              <div className="skeleton skeleton--block" />
              <div className="skeleton skeleton--block" />
              <div className="skeleton skeleton--block" />
            </div>
          ) : listQuery.isError ? (
            <p className="error-text">
              {listQuery.error instanceof ApiError
                ? listQuery.error.message
                : "Failed to load documents."}{" "}
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
