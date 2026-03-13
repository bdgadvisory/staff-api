export function apiBaseUrl(): string {
  return (import.meta as any).env?.VITE_API_BASE_URL || "http://localhost:8000";
}
export async function apiGet<T>(path: string): Promise<T> {
  const base = apiBaseUrl().replace(/\/$/, "");
  const res = await fetch(`${base}${path}`);
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`);
  return await res.json();
}
