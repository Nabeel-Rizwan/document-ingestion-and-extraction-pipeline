// Tests for useUploadQueue(): client-side upload state machine.
//
// What it does:
//   Verifies the hook tracks byte-level progress (uploading), transitions to
//   accepted/duplicate on success, and surfaces server error messages as
//   rejected.
//
// How it works:
//   - Mocks the ../api/documents uploadDocument function with vi.mock so no
//     network happens; each test programs it to report progress, resolve, or
//     reject.
//   - Uses renderHook with a QueryClientProvider wrapper, calls addFiles()
//     inside act(), then waits for items[] state with waitFor().

import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useUploadQueue } from "./useUploadQueue";
import type { Document } from "../api/types";

// Mocked uploader: tests control progress callbacks + resolution per case.
const uploadDocument = vi.fn();
vi.mock("../api/documents", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/documents")>();
  return { ...actual, uploadDocument: (...args: unknown[]) => uploadDocument(...args) };
});

// Canonical accepted document returned by the mocked upload API.
const accepted: Document = {
  id: "d1",
  filename: "a.pdf",
  mime: "application/pdf",
  size: 1,
  sha256: "a".repeat(64),
  status: "queued",
  stage: "queued",
  progress: 0,
  method: "",
  page_count: null,
  block_count: 0,
  warnings: [],
  error: "",
  error_code: "",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

// Provides the React Query context required by the hook under test.
function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

describe("useUploadQueue", () => {
  beforeEach(() => {
    // What: isolates mock call history. How: resets uploadDocument before each test.
    uploadDocument.mockReset();
  });

  it("reports byte progress then moves to accepted", async () => {
    // What: uploading state reflects onProgress fractions, then flips to
    //   accepted with progress 1 once the server responds.
    // How: programs the mock to emit 0.42 progress and hang until `finish`
    //   is called; adds a File, asserts uploading@0.42, resolves with the
    //   accepted doc, then asserts accepted@1 with id d1.
    let finish: ((value: unknown) => void) | undefined;
    uploadDocument.mockImplementation((_file: unknown, onProgress: (f: number) => void) => {
      onProgress(0.42); // simulate XHR progress event at 42%
      return new Promise((resolve) => {
        finish = resolve; // test controls when the upload completes
      });
    });

    const { result } = renderHook(() => useUploadQueue(), { wrapper });

    act(() => result.current.addFiles([new File(["x"], "a.pdf")]));

    await waitFor(() => expect(result.current.items).toHaveLength(1));
    await waitFor(() => expect(result.current.items[0].progress).toBeCloseTo(0.42));
    expect(result.current.items[0].state).toBe("uploading");

    await act(async () => {
      finish?.({ document: accepted, duplicate: false });
    });

    await waitFor(() => expect(result.current.items[0].state).toBe("accepted"));
    expect(result.current.items[0].progress).toBe(1);
    expect(result.current.items[0].document?.id).toBe("d1");
  });

  it("marks a duplicate upload", async () => {
    // What: server-reported duplicates surface as state "duplicate".
    // How: mocks an immediate resolve with duplicate:true, adds a File, and
    //   waits for the item state to become duplicate.
    uploadDocument.mockResolvedValue({ document: accepted, duplicate: true });

    const { result } = renderHook(() => useUploadQueue(), { wrapper });
    act(() => result.current.addFiles([new File(["x"], "a.pdf")]));

    await waitFor(() => expect(result.current.items[0].state).toBe("duplicate"));
  });

  it("marks a rejected upload with the error message", async () => {
    // What: server errors (e.g. 415) surface as rejected + message text.
    // How: mocks a rejection with ApiError(415, unsupported_type), adds a
    //   .bin File, waits for rejected state and asserts the message.
    const { ApiError } = await import("../api/client");
    uploadDocument.mockRejectedValue(new ApiError(415, "unsupported_type", "Unsupported file type."));

    const { result } = renderHook(() => useUploadQueue(), { wrapper });
    act(() => result.current.addFiles([new File(["x"], "a.bin")]));

    await waitFor(() => expect(result.current.items[0].state).toBe("rejected"));
    expect(result.current.items[0].error).toBe("Unsupported file type.");
  });
});
