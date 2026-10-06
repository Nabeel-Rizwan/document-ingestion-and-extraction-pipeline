import { useEffect, useMemo, useRef } from "react";
import { useParams, useSearchParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getContent } from "../api/documents";
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
    if (!data) return "";
    const pages = buildPageInfo(data.blocks);
    const textPages = pages.filter((p) => p.strategies.has("Text")).length;
    const ocrPages = pages.filter((p) => p.strategies.has("OCR")).length;
    if (pages.length === 0) return "";
    return `${pages.length} page${pages.length === 1 ? "" : "s"}: ${textPages} text, ${ocrPages} OCR`;
  }, [data]);
  if (!summary) return null;
  return <p className="routing-summary">{summary}</p>;
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
  useDocumentEvents(id, docQuery.data ? docQuery.data.status !== "done" && docQuery.data.status !== "failed" : false);

  const doc = docQuery.data;

  const contentQuery = useQuery<ContentResponse>({
    queryKey: ["content", "page", id, selectedPage],
    queryFn: () => getContent(id, "json", selectedPage ?? undefined) as Promise<ContentResponse>,
    enabled: doc?.status === "done",
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

  if (docQuery.isLoading) return <p>Loading…</p>;
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
      deleteMutation.mutate(doc.id, {
        onSuccess: () => navigate("/"),
      });
    }
  };

  const isPdf = doc.page_count !== null;
  const live = doc.status !== "done" && doc.status !== "failed";

  return (
    <div className="page document-page">
      <header className="page-header">
        <button className="btn btn--ghost btn--sm" onClick={() => navigate("/")}>
          ← Library
        </button>
        <h1>{doc.filename}</h1>
        <div className="document-page__meta">
          <span>{formatBytes(doc.size)}</span>
          <span>sha256:{doc.sha256.slice(0, 12)}…</span>
          <span>{relativeTime(doc.created_at)}</span>
        </div>
        <div className="document-page__actions">
          <a className="btn" href={`/api/documents/${doc.id}/download/`}>
            Download original
          </a>
          <button className="btn btn--danger" onClick={confirmDelete}>
            Delete
          </button>
        </div>
      </header>

      <section className="status-panel">
        <h2>Status</h2>
        <StatusBadge status={doc.status} />
        <MethodBadge method={doc.method} />
        {live ? (
          <div className="status-panel__live">
            <ProgressBar progress={doc.progress} label={`${doc.filename} progress`} />
            <p className="stage-message" aria-live="polite">
              {doc.stage}
            </p>
          </div>
        ) : doc.status === "failed" ? (
          <p className="error-text">{FAILED_MESSAGES[doc.error_code]}</p>
        ) : (
          <p className="status-panel__ok">Extraction complete.</p>
        )}
      </section>

      <WarningsPanel warnings={doc.warnings} />

      {doc.status === "done" ? (
        <div className="document-page__content">
          <RoutingSummary data={contentQuery.data} />
          <div className="document-page__body">
            {isPdf && (
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
            )}
            <div ref={contentRef} className="document-page__viewer">
              <ContentViewer document={doc} selectedPage={selectedPage} />
            </div>
          </div>
        </div>
      ) : (
        <p className="status-panel__hint">Content will appear here once processing finishes.</p>
      )}
    </div>
  );
}