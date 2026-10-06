import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { searchDocuments } from "../api/search";
import type { Document, SearchResponse } from "../api/types";
import { DocumentTable } from "../components/DocumentTable";
import { EmptyState } from "../components/EmptyState";
import { SearchBox } from "../components/SearchBox";
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

function UploadStatus({ queue }: { queue: ReturnType<typeof useUploadQueue> }) {
  const { items, remove, clear } = queue;
  if (items.length === 0) return null;
  return (
    <section className="upload-queue" data-testid="upload-queue">
      <h2>Uploads</h2>
      <button className="btn btn--ghost btn--sm" onClick={clear}>
        Clear all
      </button>
      <ul>
        {items.map((item) => (
          <li key={item.id} className="upload-item">
            <span className="upload-item__name">{item.file.name}</span>
            {item.state === "uploading" && <span className="badge badge--queued">Uploading…</span>}
            {item.state === "accepted" && (
              <span className="badge badge--done">Accepted</span>
            )}
            {item.state === "duplicate" && item.document && (
              <span className="badge badge--duplicate">
                Already uploaded —{" "}
                <Link to={`/documents/${item.document.id}`}>{item.document.filename}</Link>
              </span>
            )}
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
          </li>
        ))}
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

  return (
    <div className="page library-page">
      <header className="page-header">
        <h1>Documents</h1>
      </header>

      <UploadDropzone
        config={config.data}
        onFiles={(files) => uploadQueue.addFiles(files)}
      />
      <UploadStatus queue={uploadQueue} />

      <SearchBox onSearch={(q) => setSearchQuery(q)} />

      {searchQuery.trim().length >= 2 ? (
        searchQueryData.isLoading ? (
          <p>Searching…</p>
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
            <p>Loading documents…</p>
          ) : listQuery.isError ? (
            <p className="error-text">
              {listQuery.error instanceof ApiError ? listQuery.error.message : "Failed to load documents."}
              <button className="btn" onClick={() => void listQuery.refetch()}>
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