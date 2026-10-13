import type { Filters } from "./types";
export class APIError extends Error {
  constructor(
    public status: number,
    public data: Record<string, unknown>,
  ) {
    const detail = data.detail;
    super(
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((e) => `${e.loc?.join(".") || ""}: ${e.msg}`).join("；")
          : `请求失败（HTTP ${status}）`,
    );
  }
}
export function query(path: string, filters: Filters = {}) {
  const values = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== "") values.set(key, String(value));
  });
  return `${path}${values.size ? "?" + values : ""}`;
}
export async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch("/api" + path, options);
  if (response.status === 204) return undefined as T;
  const data = await response.json();
  if (!response.ok) throw new APIError(response.status, data);
  return data as T;
}
export const api = {
  get: <T>(path: string, signal?: AbortSignal) => request<T>(path, { signal }),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "POST",
      ...(body === undefined
        ? {}
        : {
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          }),
    }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  upload: <T>(path: string, file: File, identity: string) => {
    const body = new FormData();
    body.set("file", file);
    body.set("source_identity", identity);
    return request<T>(path, { method: "POST", body });
  },
};
export const entityPath = (kind: string, id: string) =>
  `/${kind}/${encodeURIComponent(id)}`;
export function errorText(error: unknown): string {
  return error instanceof Error ? error.message : "操作失败，请重试。";
}
export async function download(format: "json" | "markdown") {
  const response = await fetch(`/api/export?format=${format}`);
  if (!response.ok) throw new APIError(response.status, await response.json());
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = `recallnest-export.${format === "json" ? "json" : "md"}`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
