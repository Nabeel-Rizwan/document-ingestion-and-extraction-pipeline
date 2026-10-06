/** Types mirroring the backend API contract exactly. */

export type DocumentStatus = "queued" | "processing" | "done" | "failed";
export type Stage = "queued" | "detecting" | "extracting" | "indexing" | "done" | "failed";
export type Method = "" | "pdf_text" | "pdf_ocr" | "pdf_mixed" | "docx";
export type ErrorCode = "" | "corrupt" | "encrypted" | "unsupported" | "empty" | "internal";
export type BlockType = "heading" | "paragraph" | "list_item" | "table";

export interface Document {
  id: string;
  filename: string;
  mime: string;
  size: number;
  sha256: string;
  status: DocumentStatus;
  stage: Stage;
  progress: number;
  method: Method;
  page_count: number | null;
  block_count: number;
  warnings: string[];
  error: string;
  error_code: ErrorCode;
  created_at: string;
  updated_at: string;
}

export interface Block {
  id: number | null;
  idx: number;
  type: BlockType;
  text: string;
  page: number | null;
  metadata: Record<string, unknown>;
}

export interface ContentResponse {
  document_id: string;
  page_count: number | null;
  blocks: Block[];
}

export interface SearchResult {
  document_id: string;
  filename: string;
  block_id: number;
  idx: number;
  page: number | null;
  type: BlockType;
  headline: string;
  rank: number;
}

export interface SearchResponse {
  query: string;
  count: number;
  results: SearchResult[];
}

export interface SupportedFormat {
  kind: string;
  extensions: string[];
  mime_types: string[];
}

export interface AppConfig {
  max_upload_bytes: number;
  supported: SupportedFormat[];
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
  };
}

export interface UploadResponse {
  document: Document;
  duplicate: boolean;
}

export interface ListResponse {
  count: number;
  next: string | null;
  previous: string | null;
  results: Document[];
}

export interface SseEvent {
  status: DocumentStatus;
  stage: Stage;
  progress: number;
  message: string;
}

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