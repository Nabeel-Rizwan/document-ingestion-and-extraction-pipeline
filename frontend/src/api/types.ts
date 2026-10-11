/** Types mirroring the backend API contract exactly. */

// Lifecycle states shared between Document.status and the SseEvent payload.
export type DocumentStatus = "queued" | "processing" | "done" | "failed";
// Fine-grained pipeline stage a document is currently in.
export type Stage = "queued" | "detecting" | "extracting" | "indexing" | "done" | "failed";
// Extraction method; empty string means never processed. pdf_mixed = pdf_text + pdf_ocr.
export type Method = "" | "pdf_text" | "pdf_ocr" | "pdf_mixed" | "docx";
// Machine-readable failure reasons; "" marks a non-failed document.
export type ErrorCode = "" | "corrupt" | "encrypted" | "unsupported" | "empty" | "internal";
// The structural kinds a single content block can have.
export type BlockType = "heading" | "paragraph" | "list_item" | "table";
// Serialization formats the content endpoint can return.
export type ContentFormat = "json" | "markdown" | "text" | "html" | "csv";

// Full representation of a document as returned by the API.
export interface Document {
  id: string;
  filename: string;
  mime: string;
  size: number;
  // SHA-256 of the original file; used to detect duplicate uploads.
  sha256: string;
  status: DocumentStatus;
  stage: Stage;
  // 0..1 completion fraction shown in progress bars.
  progress: number;
  method: Method;
  // null until extraction has counted the pages.
  page_count: number | null;
  block_count: number;
  warnings: string[];
  // Human-readable failure message; empty when the document is not failed.
  error: string;
  error_code: ErrorCode;
  created_at: string;
  updated_at: string;
}

// A single extracted unit of content within a document.
export interface Block {
  // null for blocks that have no stored id (e.g. generated headings).
  id: number | null;
  idx: number;
  type: BlockType;
  text: string;
  // Page number the block came from; null when unknown.
  page: number | null;
  // Free-form backend metadata (e.g. table rows/columns).
  metadata: Record<string, unknown>;
}

// Shape of the JSON content response for one document/page.
export interface ContentResponse {
  document_id: string;
  page_count: number | null;
  blocks: Block[];
}

// One match within the search results list.
export interface SearchResult {
  document_id: string;
  filename: string;
  block_id: number;
  idx: number;
  // Page the match landed on; null when not applicable.
  page: number | null;
  type: BlockType;
  // Snippet of the matching block, with matches wrapped in sentinel characters.
  headline: string;
  // Relevance ordering; lower rank = stronger match.
  rank: number;
}

// Shape of the /api/search/ response.
export interface SearchResponse {
  query: string;
  count: number;
  results: SearchResult[];
}

// One entry in the app config's supported-format list.
export interface SupportedFormat {
  kind: string;
  extensions: string[];
  mime_types: string[];
}

// Shape of the /api/config/ response (limits + accepted file kinds).
export interface AppConfig {
  max_upload_bytes: number;
  supported: SupportedFormat[];
}

// The error envelope returned on non-2xx API responses.
export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
  };
}

// Shape of the upload endpoint response.
export interface UploadResponse {
  document: Document;
  // True when an identical file (same SHA-256) already exists.
  duplicate: boolean;
}

// Paginated list envelope used by the documents collection endpoint.
export interface ListResponse {
  count: number;
  // Absolute URL of the next/previous page; null when there is none.
  next: string | null;
  previous: string | null;
  results: Document[];
}

// Progress notification pushed down the SSE events stream.
export interface SseEvent {
  status: DocumentStatus;
  stage: Stage;
  progress: number;
  message: string;
}

// Tool schema descriptor for LLM agent tool calling (not used by the UI yet).
export type AgentTool = {
  type: "function";
  function: {
    name: string;
    description: string;
    parameters: {
      type: "object";
      properties: Record<string, unknown>;
      required?: string[];
    };
  };
};