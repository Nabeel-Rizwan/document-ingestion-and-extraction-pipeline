// Accessible progress bar showing a 0–1 fraction as a percentage.
export function ProgressBar({ progress, label }: { progress: number; label?: string }) {
  // Clamp the input into the 0–1 range.
  const clamped = Math.max(0, Math.min(1, progress));
  // Convert the clamped fraction to a rounded percentage.
  const percent = Math.round(clamped * 100);
  return (
    <div className="progress" data-testid="progress-bar">
      <div
        className="progress__track"
        role="progressbar"
        aria-valuenow={percent}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label ?? "Progress"}
      >
        {/* Filled portion sized to the current percentage. */}
        <div className="progress__fill" style={{ width: `${percent}%` }} />
      </div>
      {/* Numeric percentage readout. */}
      <span className="progress__value">{percent}%</span>
    </div>
  );
}
