import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useUploadQueue } from "./useUploadQueue";
import type { Document } from "../api/types";

const uploadDocument = vi.fn();
vi.mock("../api/documents", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/documents")>();
  return { ...actual, uploadDocument: (...args: unknown[]) => uploadDocument(...args) };
});

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

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

describe("useUploadQueue", () => {
  beforeEach(() => {
    uploadDocument.mockReset();
  });

  it("reports byte progress then moves to accepted", async () => {
    let finish: ((value: unknown) => void) | undefined;
    uploadDocument.mockImplementation((_file: unknown, onProgress: (f: number) => void) => {
      onProgress(0.42);
      return new Promise((resolve) => {
        finish = resolve;
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
    uploadDocument.mockResolvedValue({ document: accepted, duplicate: true });

    const { result } = renderHook(() => useUploadQueue(), { wrapper });
    act(() => result.current.addFiles([new File(["x"], "a.pdf")]));

    await waitFor(() => expect(result.current.items[0].state).toBe("duplicate"));
  });

  it("marks a rejected upload with the error message", async () => {
    const { ApiError } = await import("../api/client");
    uploadDocument.mockRejectedValue(new ApiError(415, "unsupported_type", "Unsupported file type."));

    const { result } = renderHook(() => useUploadQueue(), { wrapper });
    act(() => result.current.addFiles([new File(["x"], "a.bin")]));

    await waitFor(() => expect(result.current.items[0].state).toBe("rejected"));
    expect(result.current.items[0].error).toBe("Unsupported file type.");
  });
});
