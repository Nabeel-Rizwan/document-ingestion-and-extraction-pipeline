// React base Component class plus error and children types.
import { Component, type ErrorInfo, type ReactNode } from "react";

// Props accepted by the error boundary.
interface Props {
  // Child subtree that this boundary guards.
  children: ReactNode;
}

// Local state tracking the caught error.
interface State {
  // The error that was caught, or null when none.
  error: Error | null;
}

// Class component that catches render errors in its child subtree.
export class ErrorBoundary extends Component<Props, State> {
  // Initialize with no captured error.
  state: State = { error: null };

  // React lifecycle hook that stores the error into state on a render error.
  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  // React lifecycle hook for logging the caught error and its component stack.
  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("ErrorBoundary caught:", error, info);
  }

  render() {
    // Render the fallback UI when an error has been captured.
    if (this.state.error) {
      return (
        <div className="error-boundary" role="alert">
          <h1>Something went wrong</h1>
          {/* Display the caught error message. */}
          <p>{this.state.error.message}</p>
          {/* Reset state to retry rendering the children. */}
          <button onClick={() => this.setState({ error: null })}>Try again</button>
        </div>
      );
    }
    // Otherwise render the guarded children unchanged.
    return this.props.children;
  }
}
