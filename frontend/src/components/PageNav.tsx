/** Sidebar listing PDF pages with their text/OCR method badges. */

// Block type describing extracted content blocks.
import type { Block } from "../api/types";

// Aggregated page info: page number plus the set of strategies used.
export interface PageInfo {
  page: number;
  strategies: Set<string>;
}

// Derive per-page strategy information from a list of blocks.
export function buildPageInfo(blocks: Block[]): PageInfo[] {
  // Map each page number to the set of strategies found on it.
  const map = new Map<number, Set<string>>();
  // Walk every block to collect page/strategy pairs.
  for (const b of blocks) {
    // Skip blocks with no page association.
    if (b.page === null) continue;
    // Reuse or create the strategy set for this page.
    const set = map.get(b.page) ?? new Set<string>();
    // Read the extraction method recorded in block metadata.
    const method = b.metadata.method as string | undefined;
    // Record OCR when the block came from OCR.
    if (method === "ocr") set.add("OCR");
    // Otherwise record Text when the block came from text extraction.
    else if (method === "text") set.add("Text");
    // Store the updated set back into the map.
    map.set(b.page, set);
  }
  // Convert to an array, sort by page number, and expose strategies.
  return [...map.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([page, strategies]) => ({ page, strategies }));
}

// Sidebar navigation for selecting a page (or all pages).
export function PageNav({
  pages,
  selected,
  onSelect,
}: {
  pages: PageInfo[];
  selected: number | null;
  onSelect: (page: number | null) => void;
}) {
  return (
    <nav className="page-nav" aria-label="Pages">
      {/* "All pages" option, active when no page is selected. */}
      <button
        className={`page-nav__item${selected === null ? " page-nav__item--active" : ""}`}
        onClick={() => onSelect(null)}
      >
        All pages
      </button>
      {/* One button per page. */}
      {pages.map((p) => (
        <button
          key={p.page}
          className={`page-nav__item${selected === p.page ? " page-nav__item--active" : ""}`}
          onClick={() => onSelect(p.page)}
        >
          Page {p.page}
          <span className="page-nav__methods">
            {/* Show each strategy used on the page, sorted. */}
            {[...p.strategies].sort().map((s) => (
              <span key={s} className={`badge badge--page-${s.toLowerCase()}`}>
                {s}
              </span>
            ))}
          </span>
        </button>
      ))}
    </nav>
  );
}
