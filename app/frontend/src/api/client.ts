/**
 * The HTTP layer.
 *
 * There is no token handling anywhere in this app: the session lives in an
 * HttpOnly cookie the browser attaches on its own and JavaScript cannot read.
 * `credentials: "include"` is the whole of it.
 */

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }

  /** The session expired or was never established. */
  get isUnauthenticated(): boolean {
    return this.status === 401;
  }

  /**
   * The task broker was unreachable, so the API deliberately left the campaign
   * untouched. Worth telling apart from a real failure: nothing is broken and
   * the same request will work once the broker is back.
   */
  get isBrokerUnavailable(): boolean {
    return this.status === 503;
  }

  /** The state machine refused the transition. */
  get isConflict(): boolean {
    return this.status === 409;
  }
}

/** Where the browser goes to start Microsoft OAuth. A navigation, not a fetch. */
export const LOGIN_URL = "/auth/microsoft/login";

async function readDetail(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "detail" in body) {
      const { detail } = body;
      if (typeof detail === "string") return detail;
      // 422 from FastAPI: a list of validation errors.
      if (Array.isArray(detail)) {
        return detail
          .map((item) =>
            item && typeof item === "object" && "msg" in item
              ? String((item as { msg: unknown }).msg)
              : String(item),
          )
          .join("; ");
      }
    }
  } catch {
    // A non-JSON body (a proxy error page, say) carries nothing useful.
  }
  return response.statusText || "Request failed.";
}

interface RequestOptions {
  method?: string;
  /** Serialised as JSON. Mutually exclusive with `form`. */
  json?: unknown;
  /** Sent as multipart. The browser sets the boundary, so never set the header. */
  form?: FormData;
  signal?: AbortSignal;
}

export async function request<T>(
  path: string,
  { method = "GET", json, form, signal }: RequestOptions = {},
): Promise<T> {
  const headers: Record<string, string> = {};
  let body: BodyInit | undefined;

  if (form !== undefined) {
    body = form;
  } else if (json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(json);
  }

  const response = await fetch(path, {
    method,
    headers,
    credentials: "include",
    ...(body !== undefined ? { body } : {}),
    ...(signal ? { signal } : {}),
  });

  if (!response.ok) {
    throw new ApiError(response.status, await readDetail(response));
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}
