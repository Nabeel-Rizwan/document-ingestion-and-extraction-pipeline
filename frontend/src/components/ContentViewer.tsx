import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getContent } from "../api/documents";
import type { Block, ContentResponse, Document } from "../api/types";
import { BlockView } from "./BlockView";
import { CopyButton } from "./CopyButton";
import { EmptyState } from "./EmptyState";
import { Tabs } from "./Tabs";

const CHUNK_SIZE = 100;

export function ContentViewer({
  document,
  selectedPage,
}: {
  document: Document;
  selectedPage: number | null;
}) {
  const [tab, setTab] = useState("rendered");
  const [chunk, setChunk] = useState(CHUNK_SIZE);

  const jsonQuery = useQuery({
    queryKey: ["content", "json", document.id, selectedPage],
    queryFn: () => getContent(document.id, "json", selectedPage ?? undefined) as Promise<ContentResponse>,
    enabled: tab === "rendered" || tab === "json",
  });

  const markdownQuery = useQuery({
    queryKey: ["content", "markdown", document.id, selectedPage],
    queryFn: () => getContent(document.id, "markdown", selectedPage ?? undefined) as Promise<string>,
    enabled: tab === "markdown",
  });

  const visibleBlocks = useMemo(() => {
    if (!jsonQuery.data || document.page_count !== null) return jsonQuery.data?.blocks ?? [];
    return jsonQuery.data.blocks.slice(0, chunk);
  }, [jsonQuery.data, document.page_count, chunk]);

  const renderedPanel = () => {
    if (jsonQuery.isLoading) return <p>Loading content…</p>;
    if (jsonQuery.isError) {
      return <p className="error-text">Failed to load content.</p>;
    }
    if (!jsonQuery.data || jsonQuery.data.blocks.length === 0) {
      return <EmptyState title="No content" hint="This document produced no extractable content." />;
    }
    const blocks = document.page_count !== null ? jsonQuery.data.blocks : visibleBlocks;
    return (
      <div>
        {blocks.map((b: Block) => (
          <BlockView key={`${b.idx}-${b.id}`} block={b} />
        ))}
        {document.page_count === null && jsonQuery.data.blocks.length > chunk && (
          <button className="btn" onClick={() => setChunk((c) => c + CHUNK_SIZE)}>
            Show more
          </button>
        )}
      </div>
    );
  };

  const tabs = [
    { id: "rendered", label: "Rendered", panel: renderedPanel() },
    {
      id: "markdown",
      label: "Markdown",
      panel: (
        <div>
          <div className="content-actions">
            <CopyButton text={markdownQuery.data ?? ""} label="Copy as agent context" />
          </div>
          {markdownQuery.isLoading ? (
            <p>Loading…</p>
          ) : markdownQuery.isError ? (
            <p className="error-text">Failed to load markdown.</p>
          ) : (
            <pre className="content-pre">{markdownQuery.data}</pre>
          )}
        </div>
      ),
    },
    {
      id: "json",
      label: "JSON",
      panel: (
        <div>
          <div className="content-actions">
            <CopyButton text={jsonQuery.data ? JSON.stringify(jsonQuery.data, null, 2) : ""} />
          </div>
          {jsonQuery.isLoading ? (
            <p>Loading…</p>
          ) : jsonQuery.isError ? (
            <p className="error-text">Failed to load JSON.</p>
          ) : (
            <pre className="content-pre">{JSON.stringify(jsonQuery.data, null, 2)}</pre>
          )}
        </div>
      ),
    },
  ];

  return (
    <div className="content-viewer">
      <Tabs tabs={tabs} active={tab} onChange={(id) => setTab(id)} />
    </div>
  );
}