import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatusBadge } from "./StatusBadge";
import { ProgressBar } from "./ProgressBar";

describe("StatusBadge", () => {
  it.each(["queued", "processing", "done", "failed"] as const)(
    "renders %s",
    (status) => {
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
    render(<ProgressBar progress={0.5} label="test" />);
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "50");
    expect(bar).toHaveAttribute("aria-label", "test");
    expect(screen.getByText("50%")).toBeInTheDocument();
  });

  it("clamps values to 0..100", () => {
    const { unmount } = render(<ProgressBar progress={1.5} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
    unmount();
    render(<ProgressBar progress={-1} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "0");
  });
});