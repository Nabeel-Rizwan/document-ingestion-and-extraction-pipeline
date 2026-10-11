// React hook for local input state.
import { useState } from "react";
// Hook that debounces a rapidly changing value.
import { useDebouncedValue } from "../hooks/useDebouncedValue";

// Search input that debounces typing and triggers search callbacks.
export function SearchBox({
  onSearch,
  placeholder = "Search extracted content…",
}: {
  onSearch: (query: string) => void;
  placeholder?: string;
}) {
  // Raw text currently in the input.
  const [value, setValue] = useState("");

  // Debounced copy of the input value to avoid firing on every keystroke.
  const debounced = useDebouncedValue(value, 300);
  // Trimmed debounced query passed to the search handler.
  const query = debounced.trim();

  // Invoke the search handler only for queries of at least 2 characters.
  const fire = (q: string) => {
    if (q.length >= 2) onSearch(q);
  };

  return (
    <div className="search-box">
      <input
        type="search"
        value={value}
        placeholder={placeholder}
        aria-label="Search extracted content"
        onChange={(e) => {
          // Keep the controlled input in sync with typed text.
          setValue(e.target.value);
          // Clear results immediately when the query becomes too short.
          if (e.target.value.trim().length < 2) onSearch("");
        }}
        onKeyDown={(e) => {
          // Trigger a search when Enter is pressed.
          if (e.key === "Enter") fire(query);
        }}
      />
      {/* Explicit search button for the current query. */}
      <button className="btn" onClick={() => fire(query)}>
        Search
      </button>
    </div>
  );
}
