// Fragment for rendering plain-text headline segments without extra DOM.
import { Fragment } from "react";
// Router hook for programmatic navigation.
import { useNavigate } from "react-router-dom";
// Response and result types for the search API.
import type { SearchResponse, SearchResult } from "../api/types";
// Helper that splits a headline into highlighted and plain segments.
import { splitHeadline } from "../lib/highlight";
// Empty-state component shown when there are no matches.
import { EmptyState } from "./EmptyState";

// Renders grouped search results with highlighted matches.
export function SearchResults({ data }: { data: SearchResponse | null | undefined }) {
  // Enables navigation to a document when a result is clicked.
  const navigate = useNavigate();

  // Render nothing until data is available.
  if (!data) return null;
  // Show an empty state when there are no matches.
  if (data.count === 0) {
    return <EmptyState title="No results" hint={`Nothing matched "${data.query}".`} />;
  }

  // Group results by their source document.
  const grouped = new Map<string, { filename: string; results: SearchResult[] }>();
  // Bucket each result under its document id.
  for (const r of data.results) {
    // Reuse the existing group or create a new one for this document.
    const group = grouped.get(r.document_id) ?? { filename: r.filename, results: [] };
    group.results.push(r);
    grouped.set(r.document_id, group);
  }

  // Navigate to the matched document, preserving page and block location.
  const go = (r: SearchResult) => {
    // Build query parameters for the target page.
    const params = new URLSearchParams();
    // Include the page number when the match has one.
    if (r.page !== null) params.set("page", String(r.page));
    // Always include the block index to scroll to the match.
    params.set("block", String(r.idx));
    navigate(`/documents/${r.document_id}?${params.toString()}`);
  };

  return (
    <div className="search-results" data-testid="search-results">
      <p className="search-results__count">
        {/* Result count with correct pluralization and the query. */}
        {data.count} result{data.count === 1 ? "" : "s"} for "{data.query}"
      </p>
      {/* Render one section per document group. */}
      {[...grouped.entries()].map(([docId, group]) => (
        <section key={docId} className="search-group">
          <h3 className="search-group__title">{group.filename}</h3>
          <ul>
            {/* Render each match within the document. */}
            {group.results.map((r) => (
              <li key={r.block_id}>
                <button className="search-result" onClick={() => go(r)}>
                  <span className="search-result__meta">
                    {/* Show the page prefix only when a page is known. */}
                    {r.page !== null ? `p.${r.page} · ` : ""}
                    {r.type}
                  </span>
                  <span className="search-result__headline">
                    {/* Split the headline into highlighted and plain segments. */}
                    {splitHeadline(r.headline).map((seg, i) =>
                      seg.match ? (
                        <mark key={i}>{seg.text}</mark>
                      ) : (
                        <Fragment key={i}>{seg.text}</Fragment>
                      ),
                    )}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
