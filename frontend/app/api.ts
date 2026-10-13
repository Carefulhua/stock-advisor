export const API = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

export type CellValue = number | string | boolean | null;

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const text = await res.text();
  if (!res.ok) {
    let detail = text;
    try {
      const parsed: unknown = JSON.parse(text);
      if (parsed && typeof parsed === "object" && "detail" in parsed) {
        const d = (parsed as { detail: unknown }).detail;
        if (typeof d === "string") detail = d;
      }
    } catch {
      // 非 JSON 错误体（如代理返回的 HTML 5xx）直接原样展示
    }
    throw new Error(`请求失败(${res.status})：${detail}`);
  }
  return JSON.parse(text) as T;
}

export async function deleteJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API}${path}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`请求失败(${res.status})`);
  return (await res.json()) as T;
}

export async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API}${path}`);
  if (!res.ok) throw new Error(`请求失败(${res.status})`);
  return (await res.json()) as T;
}