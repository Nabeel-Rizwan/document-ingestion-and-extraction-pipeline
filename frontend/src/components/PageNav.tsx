/** Sidebar listing PDF pages with their text/OCR method badges. */

import type { Block } from "../api/types";

export interface PageInfo {
  page: number;
  strategies: Set<string>;
}

export function buildPageInfo(blocks: Block[]): PageInfo[] {
  const map = new Map<number, Set<string>>();
  for (const b of blocks) {
    if (b.page === null) continue;
    const set = map.get(b.page) ?? new Set<string>();
    const method = b.metadata.method as string | undefined;
    if (method === "ocr") set.add("OCR");
    else if (method === "text") set.add("Text");
    map.set(b.page, set);
  }
  return [...map.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([page, strategies]) => ({ page, strategies }));
}

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
      <button
        className={`page-nav__item${selected === null ? " page-nav__item--active" : ""}`}
        onClick={() => onSelect(null)}
      >
        All pages
      </button>
      {pages.map((p) => (
        <button
          key={p.page}
          className={`page-nav__item${selected === p.page ? " page-nav__item--active" : ""}`}
          onClick={() => onSelect(p.page)}
        >
          Page {p.page}
          <span className="page-nav__methods">
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