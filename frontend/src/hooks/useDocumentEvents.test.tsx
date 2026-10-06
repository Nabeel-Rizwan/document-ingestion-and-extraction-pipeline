import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useDocumentEvents } from "./useDocumentEvents";
import type { Document } from "../api/types";

const ID = "11111111-1111-1111-1111-111111111111";

const queuedDoc: Document = {
  id: ID,
  filename: "a.pdf",
  mime: "application/pdf",
  size: 10,
  sha256: "abc",
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

const doneDoc: Document = { ...queuedDoc, status: "done", stage: "done", progress: 1 };

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  static reset() {
    FakeEventSource.instances = [];
  }
  url: string;
  closed = false;
  onerror: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  private listeners = new Map<string, (e: MessageEvent) => void>();

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(name: string, cb: (e: MessageEvent) => void) {
    this.listeners.set(name, cb);
  }

  close() {
    this.closed = true;
  }

  fireError() {
    if (this.onerror) this.onerror(new Event("error"));
  }

  fire(name: string, data: unknown) {
    const cb = this.listeners.get(name);
    if (cb) {
      cb({ data: JSON.stringify(data) } as MessageEvent);
    }
  }
}

function Harness({ id }: { id: string }) {
  useDocumentEvents(id, true);
  return null;
}

describe("useDocumentEvents", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    queryClient.setQueryData(["document", ID], queuedDoc);
    queryClient.setQueryData(["documents", undefined], {
      count: 1,
      next: null,
      previous: null,
      results: [queuedDoc],
    });
    FakeEventSource.reset();
    vi.stubGlobal("EventSource", FakeEventSource);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("opens an EventSource and falls back to polling on error", async () => {
    const fetchMock = vi.fn(async (url: string) => {
      expect(url).toContain(`/api/documents/${ID}/`);
      return {
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => doneDoc,
        text: async () => JSON.stringify(doneDoc),
      };
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <QueryClientProvider client={queryClient}>
        <Harness id={ID} />
      </QueryClientProvider>,
    );

    expect(FakeEventSource.instances.length).toBe(1);
    const es = FakeEventSource.instances[0];
    expect(es.url).toContain("/events/");

    // Trigger an error -> should fall back to polling immediately.
    es.fireError();

    // The immediate poll fetches the terminal document and patches the cache.
    await vi.waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });

    await vi.waitFor(() => {
      const cached = queryClient.getQueryData<Document>(["document", ID]);
      expect(cached?.status).toBe("done");
    });

    // After terminal, polling stops (no interval keeps firing).
    const before = fetchMock.mock.calls.length;
    await new Promise((r) => setTimeout(r, 50));
    expect(fetchMock.mock.calls.length).toBe(before);
  });

  it("closes the EventSource on terminal events", () => {
    render(
      <QueryClientProvider client={queryClient}>
        <Harness id={ID} />
      </QueryClientProvider>,
    );
    const es = FakeEventSource.instances[0];
    es.fire("done", { status: "done", stage: "done", progress: 1, message: "Done" });
    expect(es.closed).toBe(true);
    const cached = queryClient.getQueryData<Document>(["document", ID]);
    expect(cached?.status).toBe("done");
  });
});