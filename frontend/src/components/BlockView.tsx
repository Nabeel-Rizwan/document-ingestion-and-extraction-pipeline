import type { Block } from "../api/types";

function headingTag(level: number): keyof JSX.IntrinsicElements {
  const clamped = Math.max(1, Math.min(6, level));
  return `h${clamped}` as keyof JSX.IntrinsicElements;
}

export function BlockView({ block }: { block: Block }) {
  const confidence = block.metadata.confidence as number | undefined;
  const idxAttr = { "data-block-idx": String(block.idx) };

  if (block.type === "heading") {
    const level = (block.metadata.level as number | undefined) ?? 1;
    const Tag = headingTag(level);
    return (
      <Tag className="block block--heading" {...idxAttr}>
        {block.text}
      </Tag>
    );
  }

  if (block.type === "list_item") {
    return (
      <li className="block block--list-item" {...idxAttr} data-testid="block">
        {block.text}
      </li>
    );
  }

  if (block.type === "table") {
    const rows = (block.metadata.rows as string[][] | undefined) ?? [];
    if (rows.length === 0) return null;
    const [head, ...body] = rows;
    return (
      <div className="block block--table" {...idxAttr}>
        <table data-testid="block">
          <thead>
            <tr>
              {head.map((cell, i) => (
                <th key={i}>{cell}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {body.map((row, r) => (
              <tr key={r}>
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

  const isOcr = block.metadata.method === "ocr";
  return (
    <p className="block block--paragraph" {...idxAttr} data-testid="block">
      {isOcr && (
        <span className="badge badge--ocr" title={`OCR confidence ${Math.round((confidence ?? 0) * 100)}%`}>
          OCR
        </span>
      )}
      {block.text}
    </p>
  );
}