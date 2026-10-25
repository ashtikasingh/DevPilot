export type Decision = {
  id: string;
  repository: string;
  title: string;
  content: string;
  source_path: string | null;
  created_at: string;
  updated_at: string;
};

export type DecisionList = {
  repository: string;
  decisions: Decision[];
  limit: number;
  offset: number;
};

export type DecisionCreate = {
  title: string;
  content: string;
  source_path?: string | null;
};

export type DecisionUpdate = Partial<DecisionCreate>;

type ErrorBody = {
  error?: {
    message?: unknown;
    code?: unknown;
    retry_after_seconds?: unknown;
  };
};

const DEFAULT_API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class DeveloperMemoryApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly retryAfterSeconds: number | null;

  constructor(message: string, status: number, code: string | null, retryAfterSeconds: number | null) {
    super(message);
    this.name = "DeveloperMemoryApiError";
    this.status = status;
    this.code = code;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

function endpoint(owner: string, repository: string, baseUrl = DEFAULT_API_BASE_URL): string {
  const base = baseUrl.replace(/\/$/, "");
  return `${base}/api/repositories/${encodeURIComponent(owner)}/${encodeURIComponent(repository)}/decisions`;
}

async function parseError(response: Response): Promise<DeveloperMemoryApiError> {
  let body: ErrorBody | null = null;
  try {
    body = (await response.json()) as ErrorBody;
  } catch {
    // Return a fixed safe message if the server did not return valid JSON.
  }
  const error = body?.error;
  const message = typeof error?.message === "string"
    ? error.message
    : "Developer Memory request failed. Try again shortly.";
  return new DeveloperMemoryApiError(
    message,
    response.status,
    typeof error?.code === "string" ? error.code : null,
    typeof error?.retry_after_seconds === "number" ? error.retry_after_seconds : null,
  );
}

async function requestJson<T>(
  url: string,
  init: RequestInit,
  fetcher: typeof fetch,
): Promise<T> {
  let response: Response;
  try {
    response = await fetcher(url, { ...init, cache: "no-store" });
  } catch {
    throw new DeveloperMemoryApiError(
      "Could not reach DevPilot’s API. Check that the backend is running and try again.",
      0,
      "network_error",
      null,
    );
  }

  if (!response.ok) throw await parseError(response);
  try {
    return (await response.json()) as T;
  } catch {
    throw new DeveloperMemoryApiError(
      "DevPilot returned an unexpected response. Try again shortly.",
      response.status,
      "invalid_response",
      null,
    );
  }
}

export function listDecisions(
  owner: string,
  repository: string,
  options: { fetcher?: typeof fetch; baseUrl?: string; signal?: AbortSignal } = {},
): Promise<DecisionList> {
  return requestJson<DecisionList>(endpoint(owner, repository, options.baseUrl), {
    method: "GET",
    signal: options.signal,
  }, options.fetcher ?? fetch);
}

export function createDecision(
  owner: string,
  repository: string,
  payload: DecisionCreate,
  options: { fetcher?: typeof fetch; baseUrl?: string } = {},
): Promise<Decision> {
  return requestJson<Decision>(endpoint(owner, repository, options.baseUrl), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }, options.fetcher ?? fetch);
}

export function updateDecision(
  owner: string,
  repository: string,
  decisionId: string,
  payload: DecisionUpdate,
  options: { fetcher?: typeof fetch; baseUrl?: string } = {},
): Promise<Decision> {
  return requestJson<Decision>(`${endpoint(owner, repository, options.baseUrl)}/${encodeURIComponent(decisionId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }, options.fetcher ?? fetch);
}

export async function deleteDecision(
  owner: string,
  repository: string,
  decisionId: string,
  options: { fetcher?: typeof fetch; baseUrl?: string } = {},
): Promise<void> {
  const fetcher = options.fetcher ?? fetch;
  let response: Response;
  try {
    response = await fetcher(`${endpoint(owner, repository, options.baseUrl)}/${encodeURIComponent(decisionId)}`, {
      method: "DELETE",
      cache: "no-store",
    });
  } catch {
    throw new DeveloperMemoryApiError(
      "Could not reach DevPilot’s API. Check that the backend is running and try again.",
      0,
      "network_error",
      null,
    );
  }
  if (!response.ok) throw await parseError(response);
}
