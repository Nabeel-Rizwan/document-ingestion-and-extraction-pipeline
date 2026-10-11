// React hooks used for effects, memoization, and refs.
import { useEffect, useMemo, useRef } from "react";
// Router hooks for route params, query params, and navigation.
import { useParams, useSearchParams, useNavigate } from "react-router-dom";
// React Query hook for fetching content.
import { useQuery } from "@tanstack/react-query";
// API helpers for building content URLs and fetching content.
import { contentUrl, getContent } from "../api/documents";
// Types describing content responses and error codes.
import type { ContentResponse, ErrorCode } from "../api/types";
// Typed API error for distinguishing server errors.
import { ApiError } from "../api/client";
// Child components used across the document detail page.
import { ContentViewer } from "../components/ContentViewer";
import { EmptyState } from "../components/EmptyState";
import { MethodBadge } from "../components/MethodBadge";
import { PageNav, buildPageInfo } from "../components/PageNav";
import { ProgressBar } from "../components/ProgressBar";
import { StatusBadge } from "../components/StatusBadge";
import { WarningsPanel } from "../components/WarningsPanel";
// Data hooks for loading and deleting the document.
import { useDocument, useDeleteDocument } from "../hooks/useDocuments";
// Hook subscribing to live document progress events.
import { useDocumentEvents } from "../hooks/useDocumentEvents";
// Formatting helpers for byte sizes and relative timestamps.
import { formatBytes, relativeTime } from "../lib/format";

// Human-readable messages keyed by processing error code.
const FAILED_MESSAGES: Record<ErrorCode, string> = {
  "": "Processing failed.",
  corrupt: "This file appears to be corrupt and could not be read.",
  encrypted: "This file is password-protected and could not be opened.",
  unsupported: "This file type is not supported.",
  empty: "This file was empty.",
  internal: "An unexpected error occurred during processing.",
};

// Summary of how pages were routed between text and OCR extraction.
function RoutingSummary({ data }: { data?: ContentResponse }) {
  // Derive page routing counts from the content blocks.
  const summary = useMemo(() => {
    // Nothing to summarize without content.
    if (!data) return null;
    // Aggregate per-page strategies from the blocks.
    const pages = buildPageInfo(data.blocks);
    // Nothing to show when there are no pages.
    if (pages.length === 0) return null;
    // Count pages that used text extraction.
    const textPages = pages.filter((p) => p.strategies.has("Text")).length;
    // Count pages that used OCR.
    const ocrPages = pages.filter((p) => p.strategies.has("OCR")).length;
    return { total: pages.length, textPages, ocrPages };
  }, [data]);

  // Render nothing when there is no summary.
  if (!summary) return null;
  return (
    <div className="routing-summary" data-testid="routing-summary">
      <span className="routing-summary__label">Routing</span>
      {/* Total page count with correct pluralization. */}
      <span className="badge badge--method">{summary.total} page{summary.total === 1 ? "" : "s"}</span>
      {/* Text page count, shown only when nonzero. */}
      {summary.textPages > 0 && (
        <span className="badge badge--page-text">{summary.textPages} text</span>
      )}
      {/* OCR page count, shown only when nonzero. */}
      {summary.ocrPages > 0 && <span className="badge badge--page-ocr">{summary.ocrPages} OCR</span>}
    </div>
  );
}

// Definition-list row pairing a label with a value and optional tooltip.
function MetaRow({ label, value, title }: { label: string; value: string; title?: string }) {
  return (
    <div className="meta-row">
      <dt>{label}</dt>
      {/* Value cell with an optional full-text title attribute. */}
      <dd title={title}>{value}</dd>
    </div>
  );
}

// Detail page for a single document.
export function DocumentPage() {
  // Document id from the route, defaulting to empty string.
  const { id = "" } = useParams();
  // Current query string parameters and their setter.
  const [params, setParams] = useSearchParams();
  // Router navigation helper.
  const navigate = useNavigate();
  // Selected page from the query string, or null when unset.
  const selectedPage = params.get("page") ? Number(params.get("page")) : null;
  // Target block index from the query string for scroll-to behavior.
  const targetBlock = params.get("block");
  // Ref to the content container for locating and highlighting a block.
  const contentRef = useRef<HTMLDivElement>(null);

  // Query for the document metadata.
  const docQuery = useDocument(id);
  // Mutation for deleting the document.
  const deleteMutation = useDeleteDocument();
  // Whether the document is still being processed and should stream events.
  const live = docQuery.data ? docQuery.data.status !== "done" && docQuery.data.status !== "failed" : false;
  // Subscribe to live progress events while processing.
  useDocumentEvents(id, live);

  // Convenience reference to the loaded document.
  const doc = docQuery.data;
  // Whether the document has finished processing successfully.
  const isDone = doc?.status === "done";

  // Fetch the full JSON content once processing is done.
  const contentQuery = useQuery<ContentResponse>({
    queryKey: ["content", "json", id, selectedPage],
    queryFn: () => getContent(id, "json", selectedPage ?? undefined) as Promise<ContentResponse>,
    enabled: isDone,
  });

  // Scroll to and briefly highlight the target block after content loads.
  useEffect(() => {
    if (targetBlock && contentQuery.data) {
      // Find the element tagged with the requested block index.
      const el = contentRef.current?.querySelector(`[data-block-idx="${targetBlock}"]`);
      if (el) {
        // Center the matched block in the viewport.
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        // Apply a temporary highlight style.
        el.classList.add("block--highlight");
        // Remove the highlight after 2 seconds.
        const timer = window.setTimeout(() => el.classList.remove("block--highlight"), 2000);
        // Clean up the timer if the effect re-runs or unmounts.
        return () => window.clearTimeout(timer);
      }
    }
  }, [targetBlock, contentQuery.data]);

  // Render skeleton placeholders while the document loads.
  if (docQuery.isLoading) {
    return (
      <div className="page document-page">
        <div className="skeleton skeleton--title" />
        <div className="skeleton skeleton--block" />
        <div className="skeleton skeleton--block" />
      </div>
    );
  }
  // Render a not-found state when the query errors or returns no document.
  if (docQuery.isError || !doc) {
    return (
      <EmptyState
        title="Document not found"
        hint={docQuery.error instanceof ApiError ? docQuery.error.message : "It may have been deleted."}
        action={
          <button className="btn" onClick={() => navigate("/")}>
            Back to library
          </button>
        }
      />
    );
  }

  // Confirm and delete the document, then return to the library.
  const confirmDelete = () => {
    if (window.confirm(`Delete "${doc.filename}"? This cannot be undone.`)) {
      deleteMutation.mutate(doc.id, { onSuccess: () => navigate("/") });
    }
  };

  // Whether this document is a paged PDF.
  const isPdf = doc.page_count !== null;

  return (
    <div className="page document-page">
      {/* Back link returning to the library. */}
      <button className="btn btn--ghost btn--sm back-link" onClick={() => navigate("/")}>
        ← Library
      </button>

      <header className="doc-hero card">
        <div className="doc-hero__main">
          <div className="doc-hero__badges">
            {/* Status and method badges for the document. */}
            <StatusBadge status={doc.status} />
            <MethodBadge method={doc.method} />
          </div>
          <h1>{doc.filename}</h1>
          <div className="doc-hero__meta">
            {/* Size, creation time, optional page count, and block count. */}
            <span>{formatBytes(doc.size)}</span>
            <span>·</span>
            <span>{relativeTime(doc.created_at)}</span>
            {isPdf && (
              <>
                <span>·</span>
                <span>{doc.page_count} page{doc.page_count === 1 ? "" : "s"}</span>
              </>
            )}
            <span>·</span>
            <span>{doc.block_count} block{doc.block_count === 1 ? "" : "s"}</span>
          </div>
        </div>
        <div className="doc-hero__actions">
          {/* Export the extracted content as Markdown. */}
          <a className="btn" href={contentUrl(doc.id, "markdown", { download: true })}>
            Export Markdown
          </a>
          {/* Download the originally uploaded file. */}
          <a className="btn" href={`/api/documents/${doc.id}/download/`}>
            Download original
          </a>
          {/* Delete the document after confirmation. */}
          <button className="btn btn--danger" onClick={confirmDelete}>
            Delete
          </button>
        </div>
      </header>

      {/* Live processing panel shown while the document is being processed. */}
      {live && (
        <section className="status-panel card" aria-live="polite">
          <div className="status-panel__head">
            <h2>Processing</h2>
            {/* Current processing stage. */}
            <span className="stage-message">{doc.stage}</span>
          </div>
          <ProgressBar progress={doc.progress} label={`${doc.filename} progress`} />
        </section>
      )}

      {/* Failure panel with a mapped message and raw error detail. */}
      {doc.status === "failed" && (
        <section className="status-panel status-panel--failed card" role="alert">
          <h2>Processing failed</h2>
          <p className="error-text">{FAILED_MESSAGES[doc.error_code]}</p>
          {/* Show the raw error text when present. */}
          {doc.error && <pre className="error-detail">{doc.error}</pre>}
        </section>
      )}

      {/* Two-column layout with metadata sidebar and content viewer. */}
      {isDone && (
        <div className="doc-layout">
          <aside className="doc-sidebar">
            <section className="card">
              <h2>Details</h2>
              <dl className="meta-list">
                {/* Metadata rows describing the document. */}
                <MetaRow label="Type" value={doc.mime || "—"} />
                <MetaRow label="Pages" value={doc.page_count === null ? "—" : String(doc.page_count)} />
                <MetaRow label="Blocks" value={String(doc.block_count)} />
                <MetaRow label="SHA-256" value={`${doc.sha256.slice(0, 16)}…`} title={doc.sha256} />
                <MetaRow label="Created" value={relativeTime(doc.created_at)} />
              </dl>
            </section>

            {/* Non-fatal processing warnings. */}
            <WarningsPanel warnings={doc.warnings} />

            {/* Page navigation for PDFs. */}
            {isPdf && (
              <section className="card">
                <h2>Pages</h2>
                <PageNav
                  pages={buildPageInfo(contentQuery.data?.blocks ?? [])}
                  selected={selectedPage}
                  onSelect={(page) => {
                    // Copy the current parameters before mutating.
                    const next = new URLSearchParams(params);
                    // Set or clear the page parameter.
                    if (page === null) next.delete("page");
                    else next.set("page", String(page));
                    // Clear any block anchor when changing pages.
                    next.delete("block");
                    setParams(next);
                  }}
                />
              </section>
            )}
          </aside>

          <div className="doc-content">
            {/* Routing summary above the viewer. */}
            <RoutingSummary data={contentQuery.data} />
            <div ref={contentRef}>
              {/* Content viewer wired to the fetched content and query state. */}
              <ContentViewer
                document={doc}
                selectedPage={selectedPage}
                content={contentQuery.data}
                contentLoading={contentQuery.isLoading}
                contentError={contentQuery.isError}
              />
            </div>
          </div>
        </div>
      )}

      {/* Hint shown when content is not ready and not failed. */}
      {!isDone && !live && doc.status !== "failed" && (
        <p className="status-panel__hint">Content will appear here once processing finishes.</p>
      )}
    </div>
  );
}