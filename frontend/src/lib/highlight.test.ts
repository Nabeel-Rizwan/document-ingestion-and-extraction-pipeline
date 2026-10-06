import { describe, expect, it } from "vitest";
import { splitHeadline } from "./highlight";

const START = "\u27e6";
const STOP = "\u27e7";

describe("splitHeadline", () => {
  it("splits a single match into segments", () => {
    const segments = splitHeadline(`foo ${START}bar${STOP} baz`);
    expect(segments).toEqual([
      { text: "foo ", match: false },
      { text: "bar", match: true },
      { text: " baz", match: false },
    ]);
  });

  it("handles multiple matches", () => {
    const segments = splitHeadline(`${START}a${STOP} x ${START}b${STOP}`);
    expect(segments).toEqual([
      { text: "a", match: true },
      { text: " x ", match: false },
      { text: "b", match: true },
    ]);
  });

  it("handles unbalanced markers gracefully", () => {
    const segments = splitHeadline(`${START}unclosed`);
    expect(segments).toEqual([{ text: "unclosed", match: true }]);
    expect(splitHeadline(`stray ${STOP}`)).toEqual([
      { text: "stray ", match: false },
    ]);
  });

  it("keeps <script> text inert", () => {
    const segments = splitHeadline(`${START}<script>alert(1)</script>${STOP}`);
    expect(segments).toEqual([
      { text: "<script>alert(1)</script>", match: true },
    ]);
    expect(segments.some((s) => s.text.includes("<script>"))).toBe(true);
  });

  it("returns a single plain segment for text without markers", () => {
    expect(splitHeadline("no markers here")).toEqual([
      { text: "no markers here", match: false },
    ]);
  });
});