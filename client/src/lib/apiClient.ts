export const API_BASE_PATH = '/api/v1';

export interface ApiSuccessResponse<T> {
  success: true;
  message: string;
  data: T;
}

export interface ApiErrorResponse {
  success: false;
  error: {
    code: string;
    message: string;
  };
}

export interface HealthStatusData {
  status: string;
  service: string;
  timestamp: string;
}

export class ApiClientError extends Error {
  public readonly status: number;
  public readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = 'ApiClientError';
    this.status = status;
    this.code = code;
  }
}

/**
 * Shared HTTP client anchored at /api/v1 with cookie credentials enabled.
 */
export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<ApiSuccessResponse<T>> {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  const headers = new Headers(init.headers);
  if (!headers.has('Accept')) {
    headers.set('Accept', 'application/json');
  }
  if (init.body && typeof init.body === 'string' && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const response = await fetch(`${API_BASE_PATH}${normalizedPath}`, {
    ...init,
    credentials: 'include',
    headers,
  });

  const payload = (await response.json().catch(() => null)) as
    | ApiSuccessResponse<T>
    | ApiErrorResponse
    | null;

  if (!response.ok || !payload || !payload.success) {
    const code = payload && !payload.success ? payload.error.code : 'HTTP_ERROR';
    const message =
      payload && !payload.success
        ? payload.error.message
        : `Permintaan API gagal dengan status ${response.status}`;
    throw new ApiClientError(response.status, code, message);
  }

  return payload;
}

export function fetchHealth(signal?: AbortSignal): Promise<ApiSuccessResponse<HealthStatusData>> {
  return apiFetch<HealthStatusData>('/health', { method: 'GET', signal });
}
