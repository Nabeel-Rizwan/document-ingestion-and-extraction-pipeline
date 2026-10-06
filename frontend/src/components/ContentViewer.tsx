import { useMemo, useState, type ReactNode } from "react";
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { contentUrl, getContent } from "../api/documents";
import type { Block, ContentFormat, ContentResponse, Document } from "../api/types";
import { BlockView } from "./BlockView";
import { CopyButton } from "./CopyButton";
import { EmptyState } from "./EmptyState";
import { Tabs } from "./Tabs";

/**
 * Render blocks, wrapping consecutive list items in a single `<ul>` so the
 * list structure is preserved in the DOM (and looks right).
 */
function PreviewBlocks({ blocks }: { blocks: Block[] }) {
  const nodes: ReactNode[] = [];
  let pending: Block[] = [];

  const flush = () => {
    if (pending.length === 0) return;
    nodes.push(
      <ul className="block-list" key={`list-${pending[0].idx}`}>
        {pending.map((b) => (
          <BlockView key={`${b.idx}-${b.id}`} block={b} />
        ))}
      </ul>,
    );
    pending = [];
  };

  for (const block of blocks) {
    if (block.type === "list_item") {
      pending.push(block);
      continue;
    }
    flush();
    nodes.push(<BlockView key={`${block.idx}-${block.id}`} block={block} />);
  }
  flush();

  return <>{nodes}</>;
}

const CHUNK_SIZE = 200;

interface RawFormat {
  id: Exclude<ContentFormat, "json">;
  label: string;
  filename: string;
}

const RAW_FORMATS: RawFormat[] = [
  { id: "html", label: "HTML", filename: "document.html" },
  { id: "markdown", label: "Markdown", filename: "document.md" },
  { id: "text", label: "Plain text", filename: "document.txt" },
  { id: "csv", label: "CSV", filename: "document.csv" },
];

const PREVIEW_TABS: { id: "preview" | ContentFormat; label: string }[] = [
  { id: "preview", label: "Preview" },
  { id: "html", label: "HTML" },
  { id: "markdown", label: "Markdown" },
  { id: "text", label: "Plain text" },
  { id: "csv", label: "CSV" },
  { id: "json", label: "JSON" },
];

function DownloadLink({ href, label }: { href: string; label: string }) {
  return (
    <a className="btn btn--ghost btn--sm" href={href} download data-testid="download-format">
      {label}
    </a>
  );
}

function TextPanel({
  query,
  document,
  selectedPage,
  format,
  filename,
}: {
  query: UseQueryResult<string>;
  document: Document;
  selectedPage: number | null;
  format: Exclude<ContentFormat, "json">;
  filename: string;
}) {
  const text = typeof query.data === "string" ? query.data : "";
  return (
    <div className="content-panel">
      <div className="content-actions">
        <CopyButton text={text} label="Copy" />
        <DownloadLink
          href={contentUrl(document.id, format, { page: selectedPage ?? undefined, download: true })}
          label={`Download .${filename.split(".").pop()}`}
        />
      </div>
      {query.isLoading ? (
        <p className="muted">Loading {format}…</p>
      ) : query.isError ? (
        <p className="error-text">Failed to load {format}.</p>
      ) : text.trim() === "" ? (
        <EmptyState title="No content" hint="This document produced no extractable content." />
      ) : (
        <pre className="content-pre" data-testid={`content-${format}`}>
          {text}
        </pre>
      )}
    </div>
  );
}

export function ContentViewer({
  document,
  selectedPage,
  content,
  contentLoading,
  contentError,
}: {
  document: Document;
  selectedPage: number | null;
  content?: ContentResponse;
  contentLoading?: boolean;
  contentError?: boolean;
}) {
  const [tab, setTab] = useState<string>("preview");
  const [chunk, setChunk] = useState(CHUNK_SIZE);

  const htmlQuery = useQuery<string>({
    queryKey: ["content", "html", document.id, selectedPage],
    queryFn: () => getContent(document.id, "html", selectedPage ?? undefined) as Promise<string>,
    enabled: tab === "html",
  });
  const markdownQuery = useQuery<string>({
    queryKey: ["content", "markdown", document.id, selectedPage],
    queryFn: () => getContent(document.id, "markdown", selectedPage ?? undefined) as Promise<string>,
    enabled: tab === "markdown",
  });
  const textQuery = useQuery<string>({
    queryKey: ["content", "text", document.id, selectedPage],
    queryFn: () => getContent(document.id, "text", selectedPage ?? undefined) as Promise<string>,
    enabled: tab === "text",
  });
  const csvQuery = useQuery<string>({
    queryKey: ["content", "csv", document.id, selectedPage],
    queryFn: () => getContent(document.id, "csv", selectedPage ?? undefined) as Promise<string>,
    enabled: tab === "csv",
  });

  const rawQueryFor = (format: Exclude<ContentFormat, "json">) => {
    if (format === "html") return htmlQuery;
    if (format === "markdown") return markdownQuery;
    if (format === "text") return textQuery;
    return csvQuery;
  };

  const visibleBlocks = useMemo(() => {
    if (!content) return [];
    if (document.page_count !== null) return content.blocks;
    return content.blocks.slice(0, chunk);
  }, [content, document.page_count, chunk]);

  const previewPanel = () => {
    if (contentLoading) return <p className="muted">Loading content…</p>;
    if (contentError) return <p className="error-text">Failed to load content.</p>;
    if (!content || content.blocks.length === 0) {
      return <EmptyState title="No content" hint="This document produced no extractable content." />;
    }
    return (
      <div className="content-panel">
        <div>
          <PreviewBlocks blocks={visibleBlocks} />
        </div>
        {document.page_count === null && content.blocks.length > chunk && (
          <button className="btn" onClick={() => setChunk((c) => c + CHUNK_SIZE)}>
            Show more ({content.blocks.length - chunk} remaining)
          </button>
        )}
      </div>
    );
  };

  const htmlPanel = () => {
    const source = typeof htmlQuery.data === "string" ? htmlQuery.data : "";
    return (
      <div className="content-panel">
        <div className="content-actions">
          <CopyButton text={source} label="Copy source" />
          <DownloadLink
            href={contentUrl(document.id, "html", { page: selectedPage ?? undefined, download: true })}
            label="Download .html"
          />
        </div>
        {htmlQuery.isLoading ? (
          <p className="muted">Loading HTML…</p>
        ) : htmlQuery.isError ? (
          <p className="error-text">Failed to load HTML.</p>
        ) : (
          <>
            <iframe
              className="content-frame"
              title="Rendered HTML preview"
              sandbox=""
              srcDoc={source}
            />
            <details className="content-source">
              <summary>View HTML source</summary>
              <pre className="content-pre">{source}</pre>
            </details>
          </>
        )}
      </div>
    );
  };

  const jsonPanel = () => {
    const text = content ? JSON.stringify(content, null, 2) : "";
    return (
      <div className="content-panel">
        <div className="content-actions">
          <CopyButton text={text} label="Copy" />
          <DownloadLink
            href={contentUrl(document.id, "json", { page: selectedPage ?? undefined, download: true })}
            label="Download .json"
          />
        </div>
        {contentLoading ? (
          <p className="muted">Loading JSON…</p>
        ) : contentError ? (
          <p className="error-text">Failed to load JSON.</p>
        ) : (
          <pre className="content-pre" data-testid="content-json">
            {text}
          </pre>
        )}
      </div>
    );
  };

  const panelFor = (id: string) => {
    if (id === "preview") return previewPanel();
    if (id === "json") return jsonPanel();
    if (id === "html") return htmlPanel();
    const raw = RAW_FORMATS.find((f) => f.id === id)!;
    return (
      <TextPanel
        query={rawQueryFor(raw.id)}
        document={document}
        selectedPage={selectedPage}
        format={raw.id}
        filename={raw.filename}
      />
    );
  };

  const tabs = PREVIEW_TABS.map((t) => ({ id: t.id, label: t.label, panel: panelFor(t.id) }));

  return (
    <div className="content-viewer">
      <Tabs tabs={tabs} active={tab} onChange={(id) => setTab(id)} />
    </div>
  );
}
