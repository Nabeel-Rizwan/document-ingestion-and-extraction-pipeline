/** Split a search headline on its sentinel markers into typed segments.

The backend wraps matches in U+27E6 (⟦) and U+27E7 (⟧). We split on those and
render the matched parts as <mark>. Because we build React nodes directly we
never need dangerouslySetInnerHTML, and any HTML-ish text inside a headline
stays inert.
 */

export interface HeadlineSegment {
  text: string;
  match: boolean;
}

const START = "\u27e6";
const STOP = "\u27e7";

export function splitHeadline(headline: string): HeadlineSegment[] {
  const segments: HeadlineSegment[] = [];
  let buffer = "";
  let inMatch = false;

  for (let i = 0; i < headline.length; i++) {
    const char = headline[i];
    if (char === START) {
      if (buffer) {
        segments.push({ text: buffer, match: inMatch });
        buffer = "";
      }
      inMatch = true;
    } else if (char === STOP) {
      if (buffer) {
        segments.push({ text: buffer, match: inMatch });
        buffer = "";
      }
      inMatch = false;
    } else {
      buffer += char;
    }
  }
  if (buffer) {
    segments.push({ text: buffer, match: inMatch });
  }
  return segments;
}