import { useState, type ReactNode } from "react";

interface Tab {
  id: string;
  label: string;
  panel?: ReactNode;
}

export function Tabs({
  tabs,
  active,
  onChange,
}: {
  tabs: Tab[];
  active: string;
  onChange: (id: string) => void;
}) {
  const [internal, setInternal] = useState(active);
  const selected = tabs.some((t) => t.id === active) ? active : internal;

  return (
    <div className="tabs">
      <div className="tabs__list" role="tablist" aria-label="Content views">
        {tabs.map((tab) => {
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
                setInternal(tab.id);
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
        {tabs.find((t) => t.id === selected)?.panel}
      </div>
    </div>
  );
}