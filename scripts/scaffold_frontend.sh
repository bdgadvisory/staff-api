#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

if [[ -d frontend ]]; then
  echo "frontend/ already exists; aborting."
  exit 1
fi

# 1) Scaffold Vite React TS app
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install

# 2) UI deps
npm install react-router-dom lucide-react @xyflow/react

# 3) Minimal styling (keep it simple for now; we can add Tailwind next iteration)
# Add a basic CSS file and layout.

cat > src/api.ts <<'TS'
export function apiBaseUrl(): string {
  // Prefer explicit VITE_API_BASE_URL; default to local backend
  return (import.meta as any).env?.VITE_API_BASE_URL || "http://localhost:8000";
}

export async function apiGet<T>(path: string): Promise<T> {
  const base = apiBaseUrl().replace(/\/$/, "");
  const res = await fetch(`${base}${path}`);
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`);
  return await res.json();
}
TS

cat > src/architecture/registry.ts <<'TS'
import { Cpu, Database, Shield, Bell, PlugZap, Mail } from "lucide-react";

export type ArchStatus = "ok" | "planned" | "disabled" | "degraded" | "unknown";

export type ArchNode = {
  id: string;
  name: string;
  description: string;
  status: ArchStatus;
  iconKey: "service" | "db" | "policy" | "reminders" | "integration" | "inbox";
  // optional probe config
  probe?: { kind: "http"; path: string };
};

export const iconMap = {
  service: Cpu,
  db: Database,
  policy: Shield,
  reminders: Bell,
  integration: PlugZap,
  inbox: Mail,
} as const;

export const nodes: ArchNode[] = [
  {
    id: "staff-api",
    name: "staff-api",
    description: "FastAPI service (tasks, reminders, Nestor intake)",
    status: "unknown",
    iconKey: "service",
    probe: { kind: "http", path: "/health" },
  },
  {
    id: "db",
    name: "Cloud SQL (Postgres)",
    description: "Stores tasks, reminders, nestor threads/messages",
    status: "unknown",
    iconKey: "db",
    probe: { kind: "http", path: "/db-check" },
  },
  {
    id: "reminders",
    name: "Reminders",
    description: "Create/list reminders; tick processes due reminders",
    status: "unknown",
    iconKey: "reminders",
    probe: { kind: "http", path: "/reminders" },
  },
  {
    id: "skills-gate",
    name: "Skills Policy Gate",
    description: "Allowlist + explicit enablement + exec approvals",
    status: "ok",
    iconKey: "policy",
  },
  {
    id: "agent-inbox",
    name: "Agent Inbox (future)",
    description: "Email ingestion surface (planned; high scrutiny)",
    status: "planned",
    iconKey: "inbox",
  },
  {
    id: "home-ops",
    name: "Home Ops (planned)",
    description: "Hue + Apple Home; excludes locks; natural language",
    status: "planned",
    iconKey: "integration",
  },
];
TS

cat > src/architecture/probes.ts <<'TS'
import type { ArchNode, ArchStatus } from "./registry";
import { apiGet } from "../api";

export async function probeNode(n: ArchNode): Promise<ArchStatus> {
  if (!n.probe) return n.status ?? "unknown";
  if (n.probe.kind === "http") {
    try {
      await apiGet<any>(n.probe.path);
      return "ok";
    } catch {
      return "degraded";
    }
  }
  return "unknown";
}

export async function probeAll(nodes: ArchNode[]): Promise<Record<string, ArchStatus>> {
  const out: Record<string, ArchStatus> = {};
  await Promise.all(nodes.map(async (n) => {
    out[n.id] = await probeNode(n);
  }));
  return out;
}
TS

cat > src/ArchitecturePage.tsx <<'TSX'
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
    // fixed layout for now (we can add drag-save later)
    const positions: Record<string, {x:number;y:number}> = {
      "staff-api": { x: 100, y: 80 },
      "db": { x: 420, y: 40 },
      "reminders": { x: 420, y: 140 },
      "skills-gate": { x: 100, y: 220 },
      "agent-inbox": { x: 740, y: 80 },
      "home-ops": { x: 740, y: 220 },
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
          width: 360,
        }
      };
    });
  }, [status]);

  const edges: Edge[] = [
    { id: "ui->staff-api", source: "skills-gate", target: "staff-api", label: "policy gates capability", animated: false },
    { id: "staff-api->db", source: "staff-api", target: "db", label: "SQL writes/reads", animated: false },
    { id: "staff-api->reminders", source: "staff-api", target: "reminders", label: "/reminders API", animated: false },
    { id: "reminders->tick", source: "reminders", target: "staff-api", label: "tick endpoint (internal)", animated: false },
    { id: "future->inbox", source: "staff-api", target: "agent-inbox", label: "future: email ingestion", animated: false },
    { id: "future->home", source: "staff-api", target: "home-ops", label: "future: home ops", animated: false },
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
TSX

cat > src/App.tsx <<'TSX'
import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import ArchitecturePage from "./ArchitecturePage";

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "260px 1fr", height: "100vh", background: "#070b12", color: "#e5e7eb" }}>
      <aside style={{ borderRight: "1px solid #111827", padding: 14 }}>
        <div style={{ fontWeight: 800, letterSpacing: 0.2 }}>Staff UI</div>
        <div style={{ opacity: 0.7, fontSize: 12, marginTop: 6 }}>Vite + React</div>

        <nav style={{ marginTop: 18, display: "grid", gap: 8 }}>
          <Link style={{ color: "#e5e7eb", textDecoration: "none" }} to="/architecture">Architecture</Link>
        </nav>

        <div style={{ marginTop: 18, opacity: 0.7, fontSize: 12 }}>
          API base: {import.meta.env.VITE_API_BASE_URL || "http://localhost:8000"}
        </div>
      </aside>

      <main>{children}</main>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Shell>
        <Routes>
          <Route path="/" element={<ArchitecturePage />} />
          <Route path="/architecture" element={<ArchitecturePage />} />
        </Routes>
      </Shell>
    </BrowserRouter>
  );
}
TSX

cat > src/main.tsx <<'TSX'
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
TSX

# 4) Add Makefile targets
cd ..
if ! grep -q '^ui-install:' Makefile 2>/dev/null; then
  cat >> Makefile <<'MAKE'

.PHONY: ui-install ui-dev ui-build

ui-install:
cd frontend && npm install

ui-dev:
cd frontend && npm run dev

ui-build:
cd frontend && npm run build
MAKE
fi

git add -A
git commit -m "Add frontend scaffold + architecture diagram (React Flow)" || true
git push public main
echo "Done."
