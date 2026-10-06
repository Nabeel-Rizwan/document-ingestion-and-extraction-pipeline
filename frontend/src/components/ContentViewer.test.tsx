import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ContentViewer } from "./ContentViewer";
import type { ContentResponse, Document } from "../api/types";

const getContent = vi.fn();
vi.mock("../api/documents", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/documents")>();
  return { ...actual, getContent: (...args: unknown[]) => getContent(...args) };
});

const doc: Document = {
  id: "d1",
  filename: "report.pdf",
  mime: "application/pdf",
  size: 2048,
  sha256: "a".repeat(64),
  status: "done",
  stage: "done",
  progress: 1,
  method: "pdf_text",
  page_count: 2,
  block_count: 2,
  warnings: [],
  error: "",
  error_code: "",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const content: ContentResponse = {
  document_id: "d1",
  page_count: 2,
  blocks: [
    { id: 1, idx: 0, type: "heading", text: "Title", page: 1, metadata: { level: 1 } },
    { id: 2, idx: 1, type: "paragraph", text: "Hello world", page: 1, metadata: { method: "text" } },
  ],
};

function renderViewer() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ContentViewer document={doc} selectedPage={null} content={content} />
    </QueryClientProvider>,
  );
}

describe("ContentViewer", () => {
  beforeEach(() => {
    getContent.mockReset();
  });

  it("renders blocks in the preview tab", () => {
    renderViewer();
    expect(screen.getByText("Title")).toBeInTheDocument();
    expect(screen.getByText("Hello world")).toBeInTheDocument();
  });

  it("fetches and displays a plain-text export", async () => {
    getContent.mockResolvedValue("Hello world\n");
    renderViewer();
    fireEvent.click(screen.getByRole("tab", { name: "Plain text" }));
    await waitFor(() => expect(getContent).toHaveBeenCalledWith("d1", "text", undefined));
    expect(await screen.findByTestId("content-text")).toHaveTextContent("Hello world");
  });

  it("exposes the supported export formats as tabs", () => {
    renderViewer();
    for (const label of ["Preview", "HTML", "Markdown", "Plain text", "CSV", "JSON"]) {
      expect(screen.getByRole("tab", { name: label })).toBeInTheDocument();
    }
  });

  it("offers a download link that requests the attachment", () => {
    renderViewer();
    fireEvent.click(screen.getByRole("tab", { name: "JSON" }));
    expect(screen.getByTestId("download-format")).toHaveAttribute(
      "href",
      expect.stringContaining("download=1"),
    );
  });
});
