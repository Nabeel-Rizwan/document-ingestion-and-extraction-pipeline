import { useEffect, useMemo, useRef } from "react";
import { useParams, useSearchParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { contentUrl, getContent } from "../api/documents";
import type { ContentResponse, ErrorCode } from "../api/types";
import { ApiError } from "../api/client";
import { ContentViewer } from "../components/ContentViewer";
import { EmptyState } from "../components/EmptyState";
import { MethodBadge } from "../components/MethodBadge";
import { PageNav, buildPageInfo } from "../components/PageNav";
import { ProgressBar } from "../components/ProgressBar";
import { StatusBadge } from "../components/StatusBadge";
import { WarningsPanel } from "../components/WarningsPanel";
import { useDocument, useDeleteDocument } from "../hooks/useDocuments";
import { useDocumentEvents } from "../hooks/useDocumentEvents";
import { formatBytes, relativeTime } from "../lib/format";

const FAILED_MESSAGES: Record<ErrorCode, string> = {
  "": "Processing failed.",
  corrupt: "This file appears to be corrupt and could not be read.",
  encrypted: "This file is password-protected and could not be opened.",
  unsupported: "This file type is not supported.",
  empty: "This file was empty.",
  internal: "An unexpected error occurred during processing.",
};

function RoutingSummary({ data }: { data?: ContentResponse }) {
  const summary = useMemo(() => {
    if (!data) return null;
    const pages = buildPageInfo(data.blocks);
    if (pages.length === 0) return null;
    const textPages = pages.filter((p) => p.strategies.has("Text")).length;
    const ocrPages = pages.filter((p) => p.strategies.has("OCR")).length;
    return { total: pages.length, textPages, ocrPages };
  }, [data]);

  if (!summary) return null;
  return (
    <div className="routing-summary" data-testid="routing-summary">
      <span className="routing-summary__label">Routing</span>
      <span className="badge badge--method">{summary.total} page{summary.total === 1 ? "" : "s"}</span>
      {summary.textPages > 0 && (
        <span className="badge badge--page-text">{summary.textPages} text</span>
      )}
      {summary.ocrPages > 0 && <span className="badge badge--page-ocr">{summary.ocrPages} OCR</span>}
    </div>
  );
}

function MetaRow({ label, value, title }: { label: string; value: string; title?: string }) {
  return (
    <div className="meta-row">
      <dt>{label}</dt>
      <dd title={title}>{value}</dd>
    </div>
  );
}

export function DocumentPage() {
  const { id = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const selectedPage = params.get("page") ? Number(params.get("page")) : null;
  const targetBlock = params.get("block");
  const contentRef = useRef<HTMLDivElement>(null);

  const docQuery = useDocument(id);
  const deleteMutation = useDeleteDocument();
  const live = docQuery.data ? docQuery.data.status !== "done" && docQuery.data.status !== "failed" : false;
  useDocumentEvents(id, live);

  const doc = docQuery.data;
  const isDone = doc?.status === "done";

  const contentQuery = useQuery<ContentResponse>({
    queryKey: ["content", "json", id, selectedPage],
    queryFn: () => getContent(id, "json", selectedPage ?? undefined) as Promise<ContentResponse>,
    enabled: isDone,
  });

  useEffect(() => {
    if (targetBlock && contentQuery.data) {
      const el = contentRef.current?.querySelector(`[data-block-idx="${targetBlock}"]`);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        el.classList.add("block--highlight");
        const timer = window.setTimeout(() => el.classList.remove("block--highlight"), 2000);
        return () => window.clearTimeout(timer);
      }
    }
  }, [targetBlock, contentQuery.data]);

  if (docQuery.isLoading) {
    return (
      <div className="page document-page">
        <div className="skeleton skeleton--title" />
        <div className="skeleton skeleton--block" />
        <div className="skeleton skeleton--block" />
      </div>
    );
  }
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

  const confirmDelete = () => {
    if (window.confirm(`Delete "${doc.filename}"? This cannot be undone.`)) {
      deleteMutation.mutate(doc.id, { onSuccess: () => navigate("/") });
    }
  };

  const isPdf = doc.page_count !== null;

  return (
    <div className="page document-page">
      <button className="btn btn--ghost btn--sm back-link" onClick={() => navigate("/")}>
        ← Library
      </button>

      <header className="doc-hero card">
        <div className="doc-hero__main">
          <div className="doc-hero__badges">
            <StatusBadge status={doc.status} />
            <MethodBadge method={doc.method} />
          </div>
          <h1>{doc.filename}</h1>
          <div className="doc-hero__meta">
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
          <a className="btn" href={contentUrl(doc.id, "markdown", { download: true })}>
            Export Markdown
          </a>
          <a className="btn" href={`/api/documents/${doc.id}/download/`}>
            Download original
          </a>
          <button className="btn btn--danger" onClick={confirmDelete}>
            Delete
          </button>
        </div>
      </header>

      {live && (
        <section className="status-panel card" aria-live="polite">
          <div className="status-panel__head">
            <h2>Processing</h2>
            <span className="stage-message">{doc.stage}</span>
          </div>
          <ProgressBar progress={doc.progress} label={`${doc.filename} progress`} />
        </section>
      )}

      {doc.status === "failed" && (
        <section className="status-panel status-panel--failed card" role="alert">
          <h2>Processing failed</h2>
          <p className="error-text">{FAILED_MESSAGES[doc.error_code]}</p>
          {doc.error && <pre className="error-detail">{doc.error}</pre>}
        </section>
      )}

      {isDone && (
        <div className="doc-layout">
          <aside className="doc-sidebar">
            <section className="card">
              <h2>Details</h2>
              <dl className="meta-list">
                <MetaRow label="Type" value={doc.mime || "—"} />
                <MetaRow label="Pages" value={doc.page_count === null ? "—" : String(doc.page_count)} />
                <MetaRow label="Blocks" value={String(doc.block_count)} />
                <MetaRow label="SHA-256" value={`${doc.sha256.slice(0, 16)}…`} title={doc.sha256} />
                <MetaRow label="Created" value={relativeTime(doc.created_at)} />
              </dl>
            </section>

            <WarningsPanel warnings={doc.warnings} />

            {isPdf && (
              <section className="card">
                <h2>Pages</h2>
                <PageNav
                  pages={buildPageInfo(contentQuery.data?.blocks ?? [])}
                  selected={selectedPage}
                  onSelect={(page) => {
                    const next = new URLSearchParams(params);
                    if (page === null) next.delete("page");
                    else next.set("page", String(page));
                    next.delete("block");
                    setParams(next);
                  }}
                />
              </section>
            )}
          </aside>

          <div className="doc-content">
            <RoutingSummary data={contentQuery.data} />
            <div ref={contentRef}>
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

      {!isDone && !live && doc.status !== "failed" && (
        <p className="status-panel__hint">Content will appear here once processing finishes.</p>
      )}
    </div>
  );
}
