import { Cpu, Database, Shield, Bell, PlugZap, Mail } from "lucide-react";

export type ArchStatus = "ok" | "planned" | "disabled" | "degraded" | "unknown";

export type ArchNode = {
  id: string;
  name: string;
  description: string;
  status: ArchStatus;
  iconKey: "service" | "db" | "policy" | "reminders" | "integration" | "inbox";
  probe?: { kind: "http"; path: string };
};

export const iconMap = {
  service: Cpu,
  db: Database,
  policy: Shield,
  reminders: Bell,
  integration: Plug ap,
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
