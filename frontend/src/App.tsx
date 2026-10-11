import { Link, Route, Routes } from "react-router-dom";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { DocumentPage } from "./pages/DocumentPage";
import { LibraryPage } from "./pages/LibraryPage";

// Root application component; renders the shell and sets up routing.
export function App() {
  // ErrorBoundary catches render/uncaught errors and shows a fallback UI.
  return (
    <ErrorBoundary>
      {/* Root shell: header + routed main content. */}
      <div className="app">
        <header className="app-bar">
          {/* Brand link always navigates back to the library home page. */}
          <Link to="/" className="app-bar__brand">
            {/* Decorative logo character, hidden from screen readers. */}
            <span className="app-bar__logo" aria-hidden>
              ▤
            </span>
            <span>Document Pipeline</span>
          </Link>
          <span className="app-bar__tagline">Extract · search · route PDF &amp; DOCX</span>
        </header>
        <main className="app__main">
          {/* Route matcher: only the matching <Route> element renders here. */}
          <Routes>
            {/* Home: the document library listing. */}
            <Route path="/" element={<LibraryPage />} />
            {/* Detail view for a single document, reading the id from the URL. */}
            <Route path="/documents/:id" element={<DocumentPage />} />
            {/* Unknown paths fall back to the library, avoiding blank screens. */}
            <Route path="*" element={<LibraryPage />} />
          </Routes>
        </main>
      </div>
    </ErrorBoundary>
  );
}