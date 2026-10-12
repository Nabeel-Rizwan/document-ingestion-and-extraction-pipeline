// Tests for <ContentViewer />: preview + export tabs.
//
// What it does:
//   Verifies extracted blocks render in the Preview tab, export tabs lazily
//   fetch text/HTML/markdown/CSV/JSON, consecutive list items group into one
//   <ul>, all six format tabs exist, and the download link requests an
//   attachment.
//
// How it works:
//   - Mocks ../api/documents getContent so no network happens; tests program
//     its resolved value per case.
//   - renderViewer() mounts ContentViewer inside a QueryClientProvider with a
//     canned DONE document + two blocks (heading + paragraph).
//   - Uses fireEvent.click on tab roles + waitFor/findBy for async fetches.

import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ContentViewer } from "./ContentViewer";
import type { ContentResponse, Document } from "../api/types";

// Mocked content fetcher: per-test resolve values simulate export responses.
const getContent = vi.fn();
vi.mock("../api/documents", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/documents")>();
  return { ...actual, getContent: (...args: unknown[]) => getContent(...args) };
});

// Canned DONE document owning the content under test.
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

// Canned content: one heading + one paragraph on page 1.
const content: ContentResponse = {
  document_id: "d1",
  page_count: 2,
  blocks: [
    { id: 1, idx: 0, type: "heading", text: "Title", page: 1, metadata: { level: 1 } },
    { id: 2, idx: 1, type: "paragraph", text: "Hello world", page: 1, metadata: { method: "text" } },
  ],
};

// Mounts the viewer with a fresh query client (retries off for speed).
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
    // What: isolates fetch history. How: resets the getContent mock each test.
    getContent.mockReset();
  });

  it("renders blocks in the preview tab", () => {
    // What: default Preview tab shows both block texts.
    // How: renders the viewer, asserts "Title" + "Hello world" are in the doc.
    renderViewer();
    expect(screen.getByText("Title")).toBeInTheDocument();
    expect(screen.getByText("Hello world")).toBeInTheDocument();
  });

  it("fetches and displays a plain-text export", async () => {
    // What: clicking "Plain text" lazily fetches format=text and displays it.
    // How: mocks resolve "Hello world\n", clicks the tab, waits for the call
    //   with ("d1","text",undefined), then asserts the text container content.
    getContent.mockResolvedValue("Hello world\n");
    renderViewer();
    fireEvent.click(screen.getByRole("tab", { name: "Plain text" }));
    await waitFor(() => expect(getContent).toHaveBeenCalledWith("d1", "text", undefined));
    expect(await screen.findByTestId("content-text")).toHaveTextContent("Hello world");
  });

  it("groups consecutive list items into a single list", () => {
    // What: two adjacent list_items render as one <ul> with two <li>s.
    // How: mounts the viewer with custom list content, asserts the list role
    //   is a UL with 2 items and the heading is still rendered as heading.
    const listContent: ContentResponse = {
      document_id: "d1",
      page_count: 2,
      blocks: [
        { id: 1, idx: 0, type: "heading", text: "Title", page: 1, metadata: { level: 1 } },
        { id: 2, idx: 1, type: "list_item", text: "One", page: 1, metadata: {} },
        { id: 3, idx: 2, type: "list_item", text: "Two", page: 1, metadata: {} },
      ],
    };
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <ContentViewer document={doc} selectedPage={null} content={listContent} />
      </QueryClientProvider>,
    );
    const list = screen.getByRole("list");
    expect(list.tagName).toBe("UL");
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByRole("heading", { name: "Title" })).toBeInTheDocument();
  });

  it("exposes the supported export formats as tabs", () => {
    // What: all six export affordances are present as tabs.
    // How: renders, then asserts each label Preview/HTML/Markdown/Plain
    //   text/CSV/JSON has a tab role.
    renderViewer();
    for (const label of ["Preview", "HTML", "Markdown", "Plain text", "CSV", "JSON"]) {
      expect(screen.getByRole("tab", { name: label })).toBeInTheDocument();
    }
  });

  it("offers a download link that requests the attachment", () => {
    // What: the download anchor includes download=1 for attachment headers.
    // How: clicks the JSON tab, asserts the download-format href contains
    //   the "download=1" query param.
    renderViewer();
    fireEvent.click(screen.getByRole("tab", { name: "JSON" }));
    expect(screen.getByTestId("download-format")).toHaveAttribute(
      "href",
      expect.stringContaining("download=1"),
    );
  });
});
