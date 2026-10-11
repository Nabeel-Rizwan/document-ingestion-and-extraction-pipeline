// React hooks and the ReactNode type for tab panels.
import { useState, type ReactNode } from "react";

// Shape of a single tab descriptor.
interface Tab {
  // Unique tab identifier.
  id: string;
  // Visible tab label.
  label: string;
  // Optional panel content shown when the tab is selected.
  panel?: ReactNode;
}

// Controlled/uncontrolled tabbed panel component.
export function Tabs({
  tabs,
  active,
  onChange,
}: {
  tabs: Tab[];
  active: string;
  onChange: (id: string) => void;
}) {
  // Fallback selected id used when the `active` prop is not a known tab.
  const [internal, setInternal] = useState(active);
  // Use the controlled value when valid, otherwise the internal fallback.
  const selected = tabs.some((t) => t.id === active) ? active : internal;

  return (
    <div className="tabs">
      <div className="tabs__list" role="tablist" aria-label="Content views">
        {/* Render one button per tab. */}
        {tabs.map((tab) => {
          // Whether this tab is the currently selected one.
          const isActive = tab.id === selected;
          return (
            <button
              key={tab.id}
              role="tab"
              id={`tab-${tab.id}`}
              aria-selected={isActive}
              aria-controls={`panel-${tab.id}`}
              className={`tabs__tab${isActive ? " tabs__tab--active" : ""}`}
              onClick={() => {
                // Update the internal fallback selection.
                setInternal(tab.id);
                // Notify the parent of the selection change.
                onChange(tab.id);
              }}
            >
              {tab.label}
            </button>
          );
        })}
      </div>
      <div
        className="tabs__panel"
        role="tabpanel"
        id={`panel-${selected}`}
        aria-labelledby={`tab-${selected}`}
      >
        {/* Render the selected tab's panel content. */}
        {tabs.find((t) => t.id === selected)?.panel}
      </div>
    </div>
  );
}