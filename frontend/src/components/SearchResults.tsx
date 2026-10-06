import { Fragment } from "react";
import { useNavigate } from "react-router-dom";
import type { SearchResponse, SearchResult } from "../api/types";
import { splitHeadline } from "../lib/highlight";
import { EmptyState } from "./EmptyState";

export function SearchResults({ data }: { data: SearchResponse | null | undefined }) {
  const navigate = useNavigate();

  if (!data) return null;
  if (data.count === 0) {
    return <EmptyState title="No results" hint={`Nothing matched "${data.query}".`} />;
  }

  const grouped = new Map<string, { filename: string; results: SearchResult[] }>();
  for (const r of data.results) {
    const group = grouped.get(r.document_id) ?? { filename: r.filename, results: [] };
    group.results.push(r);
    grouped.set(r.document_id, group);
  }

  const go = (r: SearchResult) => {
    const params = new URLSearchParams();
    if (r.page !== null) params.set("page", String(r.page));
    params.set("block", String(r.idx));
    navigate(`/documents/${r.document_id}?${params.toString()}`);
  };

  return (
    <div className="search-results" data-testid="search-results">
      <p className="search-results__count">
        {data.count} result{data.count === 1 ? "" : "s"} for "{data.query}"
      </p>
      {[...grouped.entries()].map(([docId, group]) => (
        <section key={docId} className="search-group">
          <h3 className="search-group__title">{group.filename}</h3>
          <ul>
            {group.results.map((r) => (
              <li key={r.block_id}>
                <button className="search-result" onClick={() => go(r)}>
                  <span className="search-result__meta">
                    {r.page !== null ? `p.${r.page} · ` : ""}
                    {r.type}
                  </span>
                  <span className="search-result__headline">
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