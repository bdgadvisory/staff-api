import type { ArchNode, ArchStatus } from "./registry";
import { apiGet } from "../api";

export async function probeNode(n: ArchNode): Promise<ArchStatus> {
  if (!n.probe) return n.status ?? "unknown";
  try {
    await apiGet<any>(n.probe.path);
    return "ok";
  } catch {
    return "degraded";
  }
}

export async function probeAll(nodes: ArchNode[]): Promise<Record<string, ArchStatus>> {
  const out: Record<string, ArchStatus> = {};
  await Promise.all(nodes.map(async (n) => {
    out[n.id] = await probeNode(n);
  }));
  return out;
}
