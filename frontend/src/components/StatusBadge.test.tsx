// Tests for <StatusBadge /> and <ProgressBar />: status + progress display.
//
// What it does:
//   Verifies every document status renders a labelled badge with the right
//   CSS modifier, and that the progress bar shows clamped percentages with
//   correct ARIA attributes for screen readers.
//
// How it works:
//   - Uses @testing-library/react render + screen queries (testid / role).
//   - StatusBadge is exercised via it.each over all four statuses.
//   - ProgressBar asserts aria-valuenow/aria-label + visible "50%" text, and
//     that out-of-range values clamp to 0..100.

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatusBadge } from "./StatusBadge";
import { ProgressBar } from "./ProgressBar";

describe("StatusBadge", () => {
  it.each(["queued", "processing", "done", "failed"] as const)(
    "renders %s",
    (status) => {
      // What: each status shows a non-empty badge with status-specific styling.
      // How: renders the badge, finds it by testid, asserts it exists, has
      //   truthy text, and its className contains `badge--<status>`.
      render(<StatusBadge status={status} />);
      const badge = screen.getByTestId("status-badge");
      expect(badge).toBeInTheDocument();
      expect(badge.textContent).toBeTruthy();
      expect(badge.className).toContain(`badge--${status}`);
    },
  );
});

describe("ProgressBar", () => {
  it("shows the percent and exposes aria-valuenow", () => {
    // What: 0.5 progress renders as 50% with labelled progressbar semantics.
    // How: renders with progress 0.5 + label, asserts role=progressbar has
    //   aria-valuenow 50 + aria-label, and "50%" text is visible.
    render(<ProgressBar progress={0.5} label="test" />);
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "50");
    expect(bar).toHaveAttribute("aria-label", "test");
    expect(screen.getByText("50%")).toBeInTheDocument();
  });

  it("clamps values to 0..100", () => {
    // What: overflow/underflow inputs clamp instead of rendering 150%/-100%.
    // How: renders 1.5 (asserts 100), unmounts, renders -1 (asserts 0).
    const { unmount } = render(<ProgressBar progress={1.5} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
    unmount();
    render(<ProgressBar progress={-1} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "0");
  });
});
