import { useEffect, useMemo, useState } from "react";
import "@xyflow/react/dist/style.css";
import { Background, Controls, MiniMap, ReactFlow, type Node, type Edge } from "@xyflow/react";
import { iconMap, nodes as registryNodes, type ArchStatus } from "./architecture/registry";
import { apiGet } from "./api";

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
  const [workflowResume, setWorkflowResume] = useState<any>(null);

  async function refresh() {
    setLoading(true);
    try {
      const r: any = await apiGet<any>("/ui/status");
      const s: Record<string, ArchStatus> = {};
      for (const n of registryNodes) {
        s[n.id] = r.components?.[n.id]?.status ?? n.status ?? "unknown";
      }
      setStatus(s);
      setWorkflowResume(r.workflow_resume ?? null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { refresh(); }, []);

  const flowNodes: Node[] = useMemo(() => {
    const positions: Record<string, {x:number;y:number}> = {
      "staff-api": { x: 80, y: 80 },
      "db": { x: 460, y: 40 },
      "reminders": { x: 460, y: 160 },
      "workflow-resume": { x: 460, y: 280 },
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
    { id: "api->wfresume", source: "staff-api", target: "workflow-resume", label: "workflow auto-resume (tick)" },
    { id: "api->inbox", source: "staff-api", target: "agent-inbox", label: "future: email ingestion" },
    { id: "api->home", source: "staff-api", target: "home-ops", label: "future: home ops" },
  ];

  return (
    <div style={{ height: "calc(100vh - 56px)", display: "flex", flexDirection: "column" }}>
      <div style={{ padding: 12, display: "flex", gap: 12, alignItems: "center" }}>
        <div style={{ fontWeight: 700 }}>Architecture</div>
        <button
          onClick={refresh}
          style={{ marginLeft: "auto", padding: "8px 12px", borderRadius: 10, background: "#111827", border: "1px solid #1f2937", color: "#e5e7eb", cursor: "pointer" }}
        >
          {loading ? "Refreshing…" : "Refresh status"}
        </button>
      </div>

      <div style={{ flex: 1, minHeight: 320 }}>
        <ReactFlow nodes={flowNodes} edges={edges} fitView>
          <MiniMap />
          <Controls />
          <Background />
        </ReactFlow>
      </div>

      <div style={{ borderTop: "1px solid #1f2937", padding: 12, background: "#070b12", color: "#e5e7eb" }}>
        <div style={{ fontWeight: 800, marginBottom: 10 }}>Workflow Auto-Resume</div>

        {(!workflowResume || !workflowResume.items || workflowResume.items.length === 0) ? (
          <div style={{ opacity: 0.8 }}>No halted workflows</div>
        ) : (
          <>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
              {[
                { label: "Halted workflows", value: workflowResume.halted_count },
                { label: "Due now", value: workflowResume.due_now_count },
                { label: "Auto-resume scheduled", value: workflowResume.auto_resume_scheduled_count },
                { label: "Manual intervention required", value: workflowResume.manual_intervention_required_count },
              ].map((c) => (
                <div key={c.label} style={{ padding: "10px 12px", borderRadius: 12, border: "1px solid #1f2937", background: "#0a0f1a", minWidth: 180 }}>
                  <div style={{ fontSize: 12, opacity: 0.8 }}>{c.label}</div>
                  <div style={{ fontSize: 20, fontWeight: 800 }}>{String(c.value ?? 0)}</div>
                </div>
              ))}
            </div>

            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                <thead>
                  <tr style={{ textAlign: "left", borderBottom: "1px solid #1f2937" }}>
                    <th style={{ padding: "8px 6px" }}>Workflow ID</th>
                    <th style={{ padding: "8px 6px" }}>Type</th>
                    <th style={{ padding: "8px 6px" }}>Department</th>
                    <th style={{ padding: "8px 6px" }}>Step</th>
                    <th style={{ padding: "8px 6px" }}>Halt reason</th>
                    <th style={{ padding: "8px 6px" }}>Next action</th>
                    <th style={{ padding: "8px 6px" }}>Next resume</th>
                    <th style={{ padding: "8px 6px" }}>Retry</th>
                    <th style={{ padding: "8px 6px" }}>Provider</th>
                    <th style={{ padding: "8px 6px" }}>Model</th>
                  </tr>
                </thead>
                <tbody>
                  {workflowResume.items.map((it: any) => {
                    const nextResume = it.next_resume_at;
                    const isManual = String(it.next_action || "").includes("manual");
                    const overdue = (() => {
                      if (!nextResume) return false;
                      const ts = Date.parse(String(nextResume));
                      if (!Number.isFinite(ts)) return false;
                      const nowMs = Date.now();
                      return (nowMs - ts) > 120_000;
                    })();

                    const rowBg = isManual ? "#2a1414" : overdue ? "#2a1d08" : "transparent";

                    return (
                      <tr key={it.workflow_id} style={{ borderBottom: "1px solid #111827", background: rowBg }}>
                        <td style={{ padding: "8px 6px", fontFamily: "monospace" }}>{it.workflow_id}</td>
                        <td style={{ padding: "8px 6px" }}>{it.workflow_type}</td>
                        <td style={{ padding: "8px 6px" }}>{it.department}</td>
                        <td style={{ padding: "8px 6px" }}>{it.current_step_id ?? it.current_step}</td>
                        <td style={{ padding: "8px 6px" }}>{it.halt_reason}</td>
                        <td style={{ padding: "8px 6px" }}>{it.next_action}</td>
                        <td style={{ padding: "8px 6px" }}>{nextResume ?? ""}</td>
                        <td style={{ padding: "8px 6px" }}>{String(it.retry_count ?? "")}</td>
                        <td style={{ padding: "8px 6px" }}>{it.provider_name ?? ""}</td>
                        <td style={{ padding: "8px 6px" }}>{it.model_name ?? ""}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
