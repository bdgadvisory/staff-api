import { useEffect, useMemo, useState } from "react";
import "@xyflow/react/dist/style.css";
import { Background, Controls, MiniMap, ReactFlow, type Node, type Edge } from "@xyflow/react";
import { iconMap, nodes as registryNodes, type ArchStatus } from "./architecture/registry";
import { probeAll } from "./architecture/probes";

function statusColor(s: ArchStatus): string {
  switch (s) {
    case "ok": return "#22c55e";
    case "planned": return "#64748b";
    case "disabled": return "#94a3b8";
    case "degraded": return "#f59e0b";
    default: return "#a1a1aa";
  }
}

export default function ArchitecturePage() {
  const [status, setStatus] = useState<Record<string, ArchStatus>>({});
  const [loading, setLoading] = useState(false);

  async function refresh() {
    setLoading(true);
    const s = await probeAll(registryNodes);
    setStatus(s);
    setLoading(false);
  }

  useEffect(() => { refresh(); }, []);

  const flowNodes: Node[] = useMemo(() => {
    const positions: Record<string, {x:number;y:number}> = {
      "staff-api": { x: 80, y: 80 },
      "db": { x: 460, y: 40 },
      "reminders": { x: 460, y: 160 },
      "skills-gate": { x: 80, y: 240 },
      "agent-inbox": { x: 840, y: 80 },
      "home-ops": { x: 840, y: 240 },
    };

    return registryNodes.map((n) => {
      const Icon = iconMap[n.iconKey];
      const s = status[n.id] ?? n.status ?? "unknown";
      return {
        id: n.id,
        position: positions[n.id] || { x: 0, y: 0 },
        data: {
          label: (
            <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
              <div style={{ width: 36, height: 36, borderRadius: 10, background: "#0b1220", display: "grid", placeItems: "center", border: `1px solid ${statusColor(s)}` }}>
                <Icon size={18} />
              </div>
              <div>
                <div style={{ fontWeight: 700 }}>{n.name}</div>
                <div style={{ opacity: 0.8, fontSize: 12, maxWidth: 260 }}>{n.description}</div>
                <div style={{ marginTop: 6, fontSize: 12, color: statusColor(s) }}>status: {s}</div>
              </div>
            </div>
          )
        },
        style: {
          background: "#0a0f1a",
          color: "#e5e7eb",
          border: "1px solid #1f2937",
          borderRadius: 14,
          padding: 10,
          width: 380,
        }
      };
    });
  }, [status]);

  const edges: Edge[] = [
    { id: "policy->api", source: "skills-gate", target: "staff-api", label: "policy gates capability" },
    { id: "api->db", source: "staff-api", target: "db", label: "SQL reads/writes" },
    { id: "api->rem", source: "staff-api", target: "reminders", label: "/reminders API" },
    { id: "rem->tick", source: "reminders", target: "staff-api", label: "tick (internal)" },
    { id: "api->inbox", source: "staff-api", target: "agent-inbox", label: "future: email ingestion" },
    { id: "api->home", source: "staff-api", target: "home-ops", label: "future: home ops" },
  ];

  return (
    <div style={{ height: "calc(100vh - 56px)" }}>
      <div style={{ padding: 12, display: "flex", gap: 12, alignItems: "center" }}>
        <div style={{ fontWeight: 700 }}>Architecture</div>
        <button
          onClick={refresh}
          style={{ marginLeft: "auto", padding: "8px 12px", borderRadius: 10, background: "#111827", border: "1px solid #1f2937", color: "#e5e7eb", cursor: "pointer" }}
        >
          {loading ? "Refreshing…" : "Refresh status"}
        </button>
      </div>

      <ReactFlow nodes={flowNodes} edges={edges} fitView>
        <MiniMap />
        <Controls />
        <Background />
      </ReactFlow>
    </div>
  );
}
