const API_BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
const API_V1 = `${API_BASE}/api/v1`;

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const TIMEOUT_MS = 10_000;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_V1}${path}`, {
      // Without this, a hung backend leaves the caller waiting forever — the UI sits in a
      // loading state that never resolves, which reads as "still working" rather than "broken".
      signal: AbortSignal.timeout(TIMEOUT_MS),
      headers: { "Content-Type": "application/json", ...init?.headers },
      ...init,
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "TimeoutError") {
      throw new ApiError(`${path} timed out after ${TIMEOUT_MS / 1000}s`, 0);
    }
    throw new ApiError(`${path} unreachable`, 0);
  }

  if (!res.ok) {
    throw new ApiError(`${init?.method ?? "GET"} ${path} failed`, res.status);
  }

  return res.json() as Promise<T>;
}

export interface HealthResponse {
  status: string;
  environment: string;
}

export interface DbHealthResponse {
  status: string;
  database: string;
}

export const api = {
  health: () => request<HealthResponse>("/health"),
  dbHealth: () => request<DbHealthResponse>("/health/db"),
};
