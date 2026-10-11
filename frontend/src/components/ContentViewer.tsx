// Hooks and types used for querying and rendering the content viewer.
import { useMemo, useState, type ReactNode } from "react";
// React Query utilities for fetching content data.
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
// API helpers for building content URLs and fetching content.
import { contentUrl, getContent } from "../api/documents";
// Types describing blocks, formats, content responses, and documents.
import type { Block, ContentFormat, ContentResponse, Document } from "../api/types";
// Child components used to render blocks, copy, empty states, and tabs.
import { BlockView } from "./BlockView";
import { CopyButton } from "./CopyButton";
import { EmptyState } from "./EmptyState";
import { Tabs } from "./Tabs";

/**
 * Render blocks, wrapping consecutive list items in a single `<ul>` so the
 * list structure is preserved in the DOM (and looks right).
 */
function PreviewBlocks({ blocks }: { blocks: Block[] }) {
  // Accumulates the final rendered nodes in document order.
  const nodes: ReactNode[] = [];
  // Holds consecutive list-item blocks until they can be flushed into a <ul>.
  let pending: Block[] = [];

  // Wrap the buffered list items in a <ul> and append it to the output.
  const flush = () => {
    // Nothing to flush when no list items are buffered.
    if (pending.length === 0) return;
    nodes.push(
      <ul className="block-list" key={`list-${pending[0].idx}`}>
        {/* Render each buffered list item as a block. */}
        {pending.map((b) => (
          <BlockView key={`${b.idx}-${b.id}`} block={b} />
        ))}
      </ul>,
    );
    // Reset the buffer after flushing.
    pending = [];
  };

  // Iterate blocks, grouping list items and flushing before other block types.
  for (const block of blocks) {
    // Buffer list items so they share one <ul>.
    if (block.type === "list_item") {
      pending.push(block);
      continue;
    }
    // Any non-list block ends the current list group.
    flush();
    // Render the non-list block directly.
    nodes.push(<BlockView key={`${block.idx}-${block.id}`} block={block} />);
  }
  // Flush any trailing list items after the loop.
  flush();

  // Render all accumulated nodes as a fragment.
  return <>{nodes}</>;
}

// Number of blocks loaded per incremental "show more" step.
const CHUNK_SIZE = 200;

// Shape of a non-JSON raw content format descriptor.
interface RawFormat {
  // Format identifier, excluding JSON.
  id: Exclude<ContentFormat, "json">;
  // Human-readable tab label.
  label: string;
  // Suggested download filename for the format.
  filename: string;
}

// Raw formats (non-JSON) offered for display and download.
const RAW_FORMATS: RawFormat[] = [
  { id: "html", label: "HTML", filename: "document.html" },
  { id: "markdown", label: "Markdown", filename: "document.md" },
  { id: "text", label: "Plain text", filename: "document.txt" },
  { id: "csv", label: "CSV", filename: "document.csv" },
];

// Ordered list of tabs shown in the content viewer.
const PREVIEW_TABS: { id: "preview" | ContentFormat; label: string }[] = [
  { id: "preview", label: "Preview" },
  { id: "html", label: "HTML" },
  { id: "markdown", label: "Markdown" },
  { id: "text", label: "Plain text" },
  { id: "csv", label: "CSV" },
  { id: "json", label: "JSON" },
];

// Anchor styled as a small ghost button that downloads a content format.
function DownloadLink({ href, label }: { href: string; label: string }) {
  return (
    <a className="btn btn--ghost btn--sm" href={href} download data-testid="download-format">
      {/* Link label text. */}
      {label}
    </a>
  );
}

// Panel that displays raw text-like content for a given format.
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
  // Use the fetched string, or an empty string while unavailable.
  const text = typeof query.data === "string" ? query.data : "";
  return (
    <div className="content-panel">
      <div className="content-actions">
        {/* Copy the fetched text to the clipboard. */}
        <CopyButton text={text} label="Copy" />
        {/* Download the same format from the API. */}
        <DownloadLink
          href={contentUrl(document.id, format, { page: selectedPage ?? undefined, download: true })}
          label={`Download .${filename.split(".").pop()}`}
        />
      </div>
      {/* Show loading, error, empty, or the text depending on query state. */}
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

// Top-level content viewer with preview and raw-format tabs.
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
  // Currently selected tab id.
  const [tab, setTab] = useState<string>("preview");
  // Number of blocks currently rendered in preview mode.
  const [chunk, setChunk] = useState(CHUNK_SIZE);

  // Lazily fetch HTML content only while the HTML tab is active.
  const htmlQuery = useQuery<string>({
    queryKey: ["content", "html", document.id, selectedPage],
    queryFn: () => getContent(document.id, "html", selectedPage ?? undefined) as Promise<string>,
    enabled: tab === "html",
  });
  // Lazily fetch Markdown content only while the Markdown tab is active.
  const markdownQuery = useQuery<string>({
    queryKey: ["content", "markdown", document.id, selectedPage],
    queryFn: () => getContent(document.id, "markdown", selectedPage ?? undefined) as Promise<string>,
    enabled: tab === "markdown",
  });
  // Lazily fetch plain text content only while the text tab is active.
  const textQuery = useQuery<string>({
    queryKey: ["content", "text", document.id, selectedPage],
    queryFn: () => getContent(document.id, "text", selectedPage ?? undefined) as Promise<string>,
    enabled: tab === "text",
  });
  // Lazily fetch CSV content only while the CSV tab is active.
  const csvQuery = useQuery<string>({
    queryKey: ["content", "csv", document.id, selectedPage],
    queryFn: () => getContent(document.id, "csv", selectedPage ?? undefined) as Promise<string>,
    enabled: tab === "csv",
  });

  // Select the query matching a raw format id.
  const rawQueryFor = (format: Exclude<ContentFormat, "json">) => {
    if (format === "html") return htmlQuery;
    if (format === "markdown") return markdownQuery;
    if (format === "text") return textQuery;
    return csvQuery;
  };

  // Blocks to display, capped to the current chunk unless pagination is disabled.
  const visibleBlocks = useMemo(() => {
    // No content yet means no blocks to show.
    if (!content) return [];
    // PDFs (with a page count) show all blocks since pages are navigable.
    if (document.page_count !== null) return content.blocks;
    // Non-paginated documents show only the first `chunk` blocks.
    return content.blocks.slice(0, chunk);
  }, [content, document.page_count, chunk]);

  // Build the preview panel, handling loading, error, and empty states.
  const previewPanel = () => {
    // Show a loading message while content is in flight.
    if (contentLoading) return <p className="muted">Loading content…</p>;
    // Show an error message when content failed to load.
    if (contentError) return <p className="error-text">Failed to load content.</p>;
    // Show an empty state when there is no content or no blocks.
    if (!content || content.blocks.length === 0) {
      return <EmptyState title="No content" hint="This document produced no extractable content." />;
    }
    return (
      <div className="content-panel">
        <div>
          {/* Render the visible blocks with list grouping. */}
          <PreviewBlocks blocks={visibleBlocks} />
        </div>
        {/* Offer incremental loading for non-paginated documents with more blocks. */}
        {document.page_count === null && content.blocks.length > chunk && (
          <button className="btn" onClick={() => setChunk((c) => c + CHUNK_SIZE)}>
            Show more ({content.blocks.length - chunk} remaining)
          </button>
        )}
      </div>
    );
  };

  // Build the HTML panel with a sandboxed iframe and source view.
  const htmlPanel = () => {
    // Use the fetched HTML string, or an empty string while unavailable.
    const source = typeof htmlQuery.data === "string" ? htmlQuery.data : "";
    return (
      <div className="content-panel">
        <div className="content-actions">
          {/* Copy the raw HTML source. */}
          <CopyButton text={source} label="Copy source" />
          {/* Download the HTML file. */}
          <DownloadLink
            href={contentUrl(document.id, "html", { page: selectedPage ?? undefined, download: true })}
            label="Download .html"
          />
        </div>
        {/* Show loading, error, or the rendered/source view. */}
        {htmlQuery.isLoading ? (
          <p className="muted">Loading HTML…</p>
        ) : htmlQuery.isError ? (
          <p className="error-text">Failed to load HTML.</p>
        ) : (
          <>
            {/* Sandboxed iframe rendering the HTML via srcDoc with no permissions. */}
            <iframe
              className="content-frame"
              title="Rendered HTML preview"
              sandbox=""
              srcDoc={source}
            />
            {/* Collapsible section showing the raw HTML source. */}
            <details className="content-source">
              <summary>View HTML source</summary>
              <pre className="content-pre">{source}</pre>
            </details>
          </>
        )}
      </div>
    );
  };

  // Build the JSON panel by pretty-printing the content response.
  const jsonPanel = () => {
    // Serialize the content response as indented JSON, or empty while loading.
    const text = content ? JSON.stringify(content, null, 2) : "";
    return (
      <div className="content-panel">
        <div className="content-actions">
          {/* Copy the JSON text. */}
          <CopyButton text={text} label="Copy" />
          {/* Download the JSON file. */}
          <DownloadLink
            href={contentUrl(document.id, "json", { page: selectedPage ?? undefined, download: true })}
            label="Download .json"
          />
        </div>
        {/* Show loading, error, or the JSON output. */}
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

  // Dispatch to the correct panel builder for a tab id.
  const panelFor = (id: string) => {
    if (id === "preview") return previewPanel();
    if (id === "json") return jsonPanel();
    if (id === "html") return htmlPanel();
    // Any remaining id must be a raw text format.
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

  // Assemble tab descriptors with their rendered panels.
  const tabs = PREVIEW_TABS.map((t) => ({ id: t.id, label: t.label, panel: panelFor(t.id) }));

  return (
    <div className="content-viewer">
      {/* Render the tab bar, wiring selection back to local state. */}
      <Tabs tabs={tabs} active={tab} onChange={(id) => setTab(id)} />
    </div>
  );
}
