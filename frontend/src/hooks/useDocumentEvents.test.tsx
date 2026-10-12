// Tests for useDocumentEvents(): SSE subscription + polling fallback.
//
// What it does:
//   Verifies the hook opens an EventSource for live progress, patches the
//   React Query cache on terminal events (done/failed), closes the stream,
//   and falls back to fetch-polling when the stream errors.
//
// How it works:
//   - FakeEventSource replaces the browser EventSource (records instances,
//     lets tests fire named events / errors on demand).
//   - A Harness component calls useDocumentEvents(id, true) inside a
//     QueryClientProvider with pre-seeded ["document", ID] cache data.
//   - Tests then fire events or errors and assert on cache updates,
//     EventSource closure, and fetch-mock polling behaviour.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useDocumentEvents } from "./useDocumentEvents";
import type { Document } from "../api/types";

const ID = "11111111-1111-1111-1111-111111111111";

// Minimal queued document used to seed the query cache before each test.
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

// Terminal DONE variant returned by the mocked poll fetch.
const doneDoc: Document = { ...queuedDoc, status: "done", stage: "done", progress: 1 };

// Fake browser EventSource: records every instance so tests can drive it.
class FakeEventSource {
  static instances: FakeEventSource[] = [];
  static reset() {
    // What: clears recorded streams between tests. How: resets the array.
    FakeEventSource.instances = [];
  }
  url: string;
  closed = false;
  onerror: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  private listeners = new Map<string, (e: MessageEvent) => void>();

  constructor(url: string) {
    // What: captures the subscribed URL. How: stores url + pushes self.
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(name: string, cb: (e: MessageEvent) => void) {
    // What: registers named SSE handlers (done/failed/progress).
    // How: stores the callback in a Map keyed by event name.
    this.listeners.set(name, cb);
  }

  close() {
    // What: marks the stream closed so tests can assert cleanup.
    // How: flips the closed flag (mirrors native EventSource.close).
    this.closed = true;
  }

  fireError() {
    // What: simulates a network/SSE failure. How: invokes onerror if set.
    if (this.onerror) this.onerror(new Event("error"));
  }

  fire(name: string, data: unknown) {
    // What: delivers one SSE event to the hook. How: looks up the listener
    //   by name and calls it with a MessageEvent carrying JSON data.
    const cb = this.listeners.get(name);
    if (cb) {
      cb({ data: JSON.stringify(data) } as MessageEvent);
    }
  }
}

// Minimal component that subscribes to document events on mount.
function Harness({ id }: { id: string }) {
  useDocumentEvents(id, true);
  return null;
}

describe("useDocumentEvents", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    // What: fresh query cache + EventSource mock per test.
    // How: creates a QueryClient with retries off, seeds the single-document
    //   and list caches with queuedDoc, resets fakes, stubs global EventSource.
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
    // What: restores real globals. How: unstubs fetch/EventSource + mocks.
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("opens an EventSource and falls back to polling on error", async () => {
    // What: stream error triggers an immediate fetch poll that resolves to
    //   DONE, patches the cache, then stops polling.
    // How: stubs fetch to return doneDoc, renders the harness, fires an SSE
    //   error, waits for fetch + cache update, then asserts no further polls
    //   fire after a 50ms quiet period.
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

    // Hook must have opened exactly one stream to the events endpoint.
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
    // What: a "done" SSE event closes the stream and marks the doc done.
    // How: renders the harness, fires done with terminal payload, asserts
    //   es.closed is true and the cached document status is "done".
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
