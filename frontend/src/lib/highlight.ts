/** Split a search headline on its sentinel markers into typed segments.

The backend wraps matches in U+27E6 (⟦) and U+27E7 (⟧). We split on those and
render the matched parts as <mark>. Because we build React nodes directly we
never need dangerouslySetInnerHTML, and any HTML-ish text inside a headline
stays inert.
 */

// One piece of a headline: plain text or a highlighted search match.
export interface HeadlineSegment {
  text: string;
  match: boolean;
}

// Sentinel characters chosen because they never occur in ordinary text.
const START = "\u27e6";
const STOP = "\u27e7";

// Tokenize a headline into alternating match/non-match segments.
export function splitHeadline(headline: string): HeadlineSegment[] {
  // Accumulated plain/matched pieces, and the current partial segment.
  const segments: HeadlineSegment[] = [];
  let buffer = "";
  let inMatch = false;

  // Walk the string char by char, toggling match state on each sentinel.
  for (let i = 0; i < headline.length; i++) {
    const char = headline[i];
    if (char === START) {
      // Flush any buffered text before entering the match region.
      if (buffer) {
        segments.push({ text: buffer, match: inMatch });
        buffer = "";
      }
      // Everything from here until STOP counts as a highlighted match.
      inMatch = true;
    } else if (char === STOP) {
      // Flush the buffered match text before leaving the match region.
      if (buffer) {
        segments.push({ text: buffer, match: inMatch });
        buffer = "";
      }
      inMatch = false;
    } else {
      // Ordinary character: accumulate into the current segment.
      buffer += char;
    }
  }
  // Flush any trailing text after the final sentinel (or run with no sentinels).
  if (buffer) {
    segments.push({ text: buffer, match: inMatch });
  }
  return segments;
}