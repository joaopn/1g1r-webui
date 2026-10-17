/**
 * The one way the app talks to the backend: same origin, JSON in and out, and an error
 * that carries the server's own message (FastAPI's `detail`) so a toast can say what went
 * wrong instead of a status code.
 */
export type Problem = { rel_path: string; problem: string };

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    /** Per-file reasons, when the server refused a plan (apply, restore). */
    readonly problems: Problem[] = [],
  ) {
    super(message);
  }
}

function problemsOf(body: unknown): Problem[] {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (detail && typeof detail === "object" && "problems" in detail) {
      const problems = (detail as { problems: unknown }).problems;
      if (Array.isArray(problems)) return problems as Problem[];
    }
  }
  return [];
}

function detailOf(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (detail && typeof detail === "object" && "message" in detail)
      return String((detail as { message: unknown }).message);
    if (Array.isArray(detail)) {
      return detail
        .map((item) => (item && typeof item === "object" && "msg" in item ? String(item.msg) : ""))
        .filter(Boolean)
        .join("; ");
    }
  }
  return fallback;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  const response = await fetch(`/api${path}`, { ...init, headers });
  const text = await response.text();
  const body: unknown = text ? JSON.parse(text) : undefined;
  if (!response.ok)
    throw new ApiError(detailOf(body, response.statusText), response.status, problemsOf(body));
  return body as T;
}

export const json = (method: string, body: unknown): RequestInit => ({
  method,
  body: JSON.stringify(body),
});

export function upload(file: File): RequestInit {
  const form = new FormData();
  form.append("file", file);
  return { method: "POST", body: form };
}
