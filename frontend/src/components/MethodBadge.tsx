import type { Method } from "../api/types";

const LABELS: Record<Method, string> = {
  "": "",
  pdf_text: "Text",
  pdf_ocr: "OCR",
  pdf_mixed: "Text + OCR",
  docx: "DOCX",
};

export function MethodBadge({ method }: { method: Method }) {
  if (!method) return null;
  return <span className={`badge badge--method badge--method-${method}`}>{LABELS[method]}</span>;
}