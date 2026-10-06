import { Link, Route, Routes } from "react-router-dom";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { DocumentPage } from "./pages/DocumentPage";
import { LibraryPage } from "./pages/LibraryPage";

export function App() {
  return (
    <ErrorBoundary>
      <div className="app">
        <header className="app-bar">
          <Link to="/" className="app-bar__brand">
            <span className="app-bar__logo" aria-hidden>
              ▤
            </span>
            <span>Document Pipeline</span>
          </Link>
          <span className="app-bar__tagline">Extract · search · route PDF &amp; DOCX</span>
        </header>
        <main className="app__main">
          <Routes>
            <Route path="/" element={<LibraryPage />} />
            <Route path="/documents/:id" element={<DocumentPage />} />
            <Route path="*" element={<LibraryPage />} />
          </Routes>
        </main>
      </div>
    </ErrorBoundary>
  );
}
