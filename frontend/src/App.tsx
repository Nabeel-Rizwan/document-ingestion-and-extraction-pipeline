import { Route, Routes } from "react-router-dom";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { DocumentPage } from "./pages/DocumentPage";
import { LibraryPage } from "./pages/LibraryPage";

export function App() {
  return (
    <ErrorBoundary>
      <div className="app">
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