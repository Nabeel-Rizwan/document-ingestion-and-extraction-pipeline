// Import the Block type describing a single extracted content block.
import type { Block } from "../api/types";

// Map an arbitrary heading level to a valid HTML heading tag name (h1–h6).
function headingTag(level: number): keyof JSX.IntrinsicElements {
  // Clamp the level into the 1–6 range supported by HTML headings.
  const clamped = Math.max(1, Math.min(6, level));
  // Return the tag name as a typed intrinsic element key.
  return `h${clamped}` as keyof JSX.IntrinsicElements;
}

// Render a single block, choosing markup based on the block's type.
export function BlockView({ block }: { block: Block }) {
  // OCR confidence value from metadata, used for the badge tooltip when present.
  const confidence = block.metadata.confidence as number | undefined;
  // Spreadable attribute exposing the block index in the DOM for scroll/lookup.
  const idxAttr = { "data-block-idx": String(block.idx) };

  // Heading blocks render as the matching h1–h6 element.
  if (block.type === "heading") {
    // Heading level from metadata, defaulting to 1 when unset.
    const level = (block.metadata.level as number | undefined) ?? 1;
    // Resolve the concrete heading tag component for this level.
    const Tag = headingTag(level);
    return (
      <Tag className="block block--heading" {...idxAttr}>
        {/* Heading text content. */}
        {block.text}
      </Tag>
    );
  }

  // List items render as <li>; the parent groups them in a <ul>.
  if (block.type === "list_item") {
    return (
      <li className="block block--list-item" {...idxAttr} data-testid="block">
        {/* List item text content. */}
        {block.text}
      </li>
    );
  }

  // Table blocks render a thead from the first row and a tbody from the rest.
  if (block.type === "table") {
    // Read the 2D row/cell array from metadata, defaulting to empty.
    const rows = (block.metadata.rows as string[][] | undefined) ?? [];
    // Render nothing when the table has no rows.
    if (rows.length === 0) return null;
    // Destructure the header row from the remaining body rows.
    const [head, ...body] = rows;
    return (
      <div className="block block--table" {...idxAttr}>
        <table data-testid="block">
          <thead>
            <tr>
              {/* Render each header cell, keyed by column position. */}
              {head.map((cell, i) => (
                <th key={i}>{cell}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {/* Render each body row, keyed by row index. */}
            {body.map((row, r) => (
              <tr key={r}>
                {/* Render each cell in the row, keyed by column index. */}
                {row.map((cell, c) => (
                  <td key={c}>{cell}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  // Any other block type falls through to a paragraph.
  const isOcr = block.metadata.method === "ocr";
  return (
    <p className="block block--paragraph" {...idxAttr} data-testid="block">
      {/* Show an OCR badge only when this block was produced by OCR. */}
      {isOcr && (
        <span className="badge badge--ocr" title={`OCR confidence ${Math.round((confidence ?? 0) * 100)}%`}>
          OCR
        </span>
      )}
      {/* Paragraph text content. */}
      {block.text}
    </p>
  );
}
