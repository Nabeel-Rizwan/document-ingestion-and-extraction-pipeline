import { useState } from "react";
import { useDebouncedValue } from "../hooks/useDebouncedValue";

export function SearchBox({
  onSearch,
  placeholder = "Search extracted content…",
}: {
  onSearch: (query: string) => void;
  placeholder?: string;
}) {
  const [value, setValue] = useState("");

  const debounced = useDebouncedValue(value, 300);
  const query = debounced.trim();

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
          setValue(e.target.value);
          if (e.target.value.trim().length < 2) onSearch("");
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") fire(query);
        }}
      />
      <button className="btn" onClick={() => fire(query)}>
        Search
      </button>
    </div>
  );
}