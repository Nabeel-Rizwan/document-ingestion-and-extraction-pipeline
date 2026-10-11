import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App";
import "./styles.css";

// Create the shared react-query client used by every query/mutation in the app.
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Data is considered fresh for 5 seconds, reducing redundant network calls.
      staleTime: 5_000,
      // Failed queries are retried once automatically before surfacing the error.
      retry: 1,
    },
  },
});

// Mount React into the #root element; the non-null assertion trusts the index.html markup.
ReactDOM.createRoot(document.getElementById("root")!).render(
  // StrictMode double-invokes effects in development to surface side-effect bugs.
  <React.StrictMode>
    {/* Provide the query client to all descendant hooks (useQuery/useMutation). */}
    <QueryClientProvider client={queryClient}>
      {/* Router that syncs the URL with <Routes> so navigation works without a server. */}
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);