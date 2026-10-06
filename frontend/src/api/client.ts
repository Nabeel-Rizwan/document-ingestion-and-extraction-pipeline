/** Fetch wrapper that parses the contract's error envelope into ApiError. */

import type { ApiErrorBody } from "./types";

export class ApiError extends Error {
  status: number;
  code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

async function parseBody(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

/** Turn an HTTP status + parsed body into an ApiError (contract envelope aware). */
export function toApiError(status: number, body: unknown): ApiError {
  if (isErrorBody(body)) {
    return new ApiError(status, body.error.code, body.error.message);
  }
  if (typeof body === "string") {
    return new ApiError(status, "bad_request", body);
  }
  return new ApiError(status, "bad_request", "Request failed.");
}

export async function apiRequest<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch (err) {
    throw new ApiError(0, "network", "Network error; please try again.");
  }

  const body = await parseBody(response);

  if (!response.ok) {
    throw toApiError(response.status, body);
  }

  return body as T;
}

function isErrorBody(body: unknown): body is ApiErrorBody {
  return (
    typeof body === "object" &&
    body !== null &&
    "error" in body &&
    typeof (body as ApiErrorBody).error === "object"
  );
}