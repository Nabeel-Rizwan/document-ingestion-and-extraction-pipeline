// Tests for splitHeadline(): search-highlight segmentation.
//
// What it does:
//   Verifies that backend headline markers (⟦ START / ⟧ STOP) are split into
//   { text, match } segments for highlighted rendering, including edge cases
//   (multiple matches, unbalanced markers, inert <script> text, no markers).
//
// How it works:
//   - Calls the pure function splitHeadline() with crafted strings and asserts
//     with toEqual on the exact segment arrays.
//   - No DOM, no mocks needed: these are fast unit tests around string parsing.

import { describe, expect, it } from "vitest";
import { splitHeadline } from "./highlight";

// Marker constants mirror the backend search headline delimiters.
const START = "⟦";
const STOP = "⟧";

describe("splitHeadline", () => {
  it("splits a single match into segments", () => {
    // What: one highlighted word between plain text on both sides.
    // How: splits "foo ⟦bar⟧ baz", asserts 3 segments with middle match:true.
    const segments = splitHeadline(`foo ${START}bar${STOP} baz`);
    expect(segments).toEqual([
      { text: "foo ", match: false },
      { text: "bar", match: true },
      { text: " baz", match: false },
    ]);
  });

  it("handles multiple matches", () => {
    // What: two separate highlights with plain text between them.
    // How: splits "⟦a⟧ x ⟦b⟧", asserts [match, plain, match] in order.
    const segments = splitHeadline(`${START}a${STOP} x ${START}b${STOP}`);
    expect(segments).toEqual([
      { text: "a", match: true },
      { text: " x ", match: false },
      { text: "b", match: true },
    ]);
  });

  it("handles unbalanced markers gracefully", () => {
    // What: malformed markers never crash or drop text.
    // How: unclosed START treats rest as a match; stray STOP is stripped and
    //   the preceding text stays a single plain segment.
    const segments = splitHeadline(`${START}unclosed`);
    expect(segments).toEqual([{ text: "unclosed", match: true }]);
    expect(splitHeadline(`stray ${STOP}`)).toEqual([
      { text: "stray ", match: false },
    ]);
  });

  it("keeps <script> text inert", () => {
    // What: XSS guard - script tags inside a match are returned as inert text,
    //   never executed (React escapes them at render time).
    // How: splits a ⟦<script>…⟧ headline, asserts the single match segment
    //   still contains the literal "<script>" string for the escape test.
    const segments = splitHeadline(`${START}<script>alert(1)</script>${STOP}`);
    expect(segments).toEqual([
      { text: "<script>alert(1)</script>", match: true },
    ]);
    expect(segments.some((s) => s.text.includes("<script>"))).toBe(true);
  });

  it("returns a single plain segment for text without markers", () => {
    // What: headlines with no highlights pass through as one plain segment.
    // How: splits "no markers here", asserts [{ text, match:false }].
    expect(splitHeadline("no markers here")).toEqual([
      { text: "no markers here", match: false },
    ]);
  });
});
