import type { ArchNode, ArchStatus } from "./registry";
import { apiGet } from "../api";

type UiStatusResponse = {
  ok: boolean;
  components: Record<string, { status: ArchStatus; error?: string }>;
};

export async function probeAll(nodes: ArchNode[]): Promise<Record<string, ArchStatus>> {
  const out: Record<string, ArchStatus> = {};
  try {
    const r = await apiGet<UiStatusResponse>("/ui/status");
    for (const n of nodes) {
      out[n.id] = r.components?.[n.id]?.status ?? n.status ?? "unknown";
    }
    return out;
  } catch {
    // If UI can't reach the backend at all, mark probed nodes as degraded.
    for (const n of nodes) {
      out[n.id] = n.probe ? "degraded" : (n.status ?? "unknown");
    }
    return out;
  }
}
