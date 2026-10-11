// React hook for local component state.
import { useState } from "react";

// Button that copies `text` to the clipboard and briefly shows feedback.
export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  // Whether the text was recently copied, used to swap the label.
  const [copied, setCopied] = useState(false);

  // Write the text to the clipboard and toggle the copied state.
  const copy = async () => {
    try {
      // Copy the provided text via the async Clipboard API.
      await navigator.clipboard.writeText(text);
      // Flag success so the label shows "Copied".
      setCopied(true);
      // Reset the flag after 1.5 seconds.
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // On failure, ensure the copied flag is cleared.
      setCopied(false);
    }
  };

  return (
    <button className="btn btn--ghost" onClick={copy} data-testid="copy-button">
      {/* Show "Copied" briefly, otherwise the provided label. */}
      {copied ? "Copied" : label}
    </button>
  );
}
