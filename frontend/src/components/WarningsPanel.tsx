// Panel listing non-fatal warnings from document processing.
export function WarningsPanel({ warnings }: { warnings: string[] }) {
  // Render nothing when there are no warnings.
  if (!warnings || warnings.length === 0) return null;
  return (
    <div className="warnings" data-testid="warnings-panel">
      <h3>Warnings</h3>
      <ul>
        {/* Render each warning as a list item. */}
        {warnings.map((w, i) => (
          <li key={i}>{w}</li>
        ))}
      </ul>
    </div>
  );
}