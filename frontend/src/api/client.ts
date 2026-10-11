/** Fetch wrapper that parses the contract's error envelope into ApiError. */

import type { ApiErrorBody } from "./types";

// Typed error subclass carrying HTTP status + machine-readable error code.
export class ApiError extends Error {
  status: number;
  code: string;

  constructor(status: number, code: string, message: string) {
    // Initialize the Error base class with the human-readable message.
    super(message);
    // Keep Error.prototype.name accurate for logging/inspection.
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

// Parse a fetch Response body into unknown; JSON content becomes an object,
// anything else is returned as a raw text string.
async function parseBody(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

/** Turn an HTTP status + parsed body into an ApiError (contract envelope aware). */
export function toApiError(status: number, body: unknown): ApiError {
  // Prefer the structured { error: { code, message } } envelope when present.
  if (isErrorBody(body)) {
    return new ApiError(status, body.error.code, body.error.message);
  }
  // Fall back to using the raw server text as the message.
  if (typeof body === "string") {
    return new ApiError(status, "bad_request", body);
  }
  // Last resort for unexpected bodies.
  return new ApiError(status, "bad_request", "Request failed.");
}

// Generic GET/POST wrapper that types the response body as T and normalizes
// both network failures and non-2xx responses into ApiError.
export async function apiRequest<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch (err) {
    // fetch only rejects on network-level failures (no HTTP response at all).
    throw new ApiError(0, "network", "Network error; please try again.");
  }

  // Read the body first so it is available for error construction below.
  const body = await parseBody(response);

  // Non-2xx responses still carry a (usually JSON) body; convert it to ApiError.
  if (!response.ok) {
    throw toApiError(response.status, body);
  }

  // Cast the parsed body to the caller's expected shape.
  return body as T;
}

// Runtime guard: true only when body is a non-null object with an `error`
// property that is itself an object, i.e. the contract envelope.
function isErrorBody(body: unknown): body is ApiErrorBody {
  return (
    typeof body === "object" &&
    body !== null &&
    "error" in body &&
    typeof (body as ApiErrorBody).error === "object"
  );
}