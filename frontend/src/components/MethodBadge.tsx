// Method type enumerating extraction strategies.
import type { Method } from "../api/types";

// Map each method value to its display label.
const LABELS: Record<Method, string> = {
  "": "",
  pdf_text: "Text",
  pdf_ocr: "OCR",
  pdf_mixed: "Text + OCR",
  docx: "DOCX",
};

// Badge showing a document's extraction method.
export function MethodBadge({ method }: { method: Method }) {
  // Render nothing when no method is set.
  if (!method) return null;
  // Render a method-specific styled badge using the mapped label.
  return <span className={`badge badge--method badge--method-${method}`}>{LABELS[method]}</span>;
}
