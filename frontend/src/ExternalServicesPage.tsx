import { useEffect, useState } from "react";
import { apiGet } from "./api";

export default function ExternalServicesPage() {
  const [summary, setSummary] = useState<any>(null);
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  async function refresh() {
    setLoading(true);
    try {
      const s = await apiGet<any>("/api/external-services/summary");
      const l = await apiGet<any>("/api/external-services");
      setSummary(s);
      setItems(l.items || []);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { refresh(); }, []);

  return (
    <div style={{ padding: 16 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
        <div style={{ fontSize: 20, fontWeight: 900 }}>External Services</div>
        <div style={{ opacity: 0.7 }}>Live usage, health, auth, billing, and routing control for all third-party services.</div>
        <button
          onClick={refresh}
          style={{ marginLeft: "auto", padding: "8px 12px", borderRadius: 10, background: "#111827", border: "1px solid #1f2937", color: "#e5e7eb", cursor: "pointer" }}
        >
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 14 }}>
        {[
          { label: "External Services Total", value: summary?.total_services ?? 0 },
          { label: "Healthy", value: Math.max((summary?.enabled ?? 0) - (summary?.warnings ?? 0), 0) },
          { label: "Warnings / Degraded", value: summary?.warnings ?? 0 },
          { label: "Billing Issues", value: summary?.billing_issues ?? 0 },
          { label: "Estimated Spend This Period", value: `${summary?.estimated_spend ?? 0} ${summary?.currency ?? "USD"}` },
        ].map((c) => (
          <div key={c.label} style={{ padding: "10px 12px", borderRadius: 12, border: "1px solid #1f2937", background: "#0a0f1a", minWidth: 220 }}>
            <div style={{ fontSize: 12, opacity: 0.8 }}>{c.label}</div>
            <div style={{ fontSize: 18, fontWeight: 900 }}>{String(c.value)}</div>
          </div>
        ))}
      </div>

      <div style={{ marginTop: 16, border: "1px solid #1f2937", borderRadius: 12, overflow: "hidden" }}>
        <div style={{ padding: 10, fontWeight: 800, background: "#0a0f1a", borderBottom: "1px solid #1f2937" }}>Services</div>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
            <thead>
              <tr style={{ textAlign: "left", borderBottom: "1px solid #1f2937" }}>
                <th style={{ padding: "8px 6px" }}>Service Name</th>
                <th style={{ padding: "8px 6px" }}>Vendor</th>
                <th style={{ padding: "8px 6px" }}>Category</th>
                <th style={{ padding: "8px 6px" }}>Enabled</th>
                <th style={{ padding: "8px 6px" }}>Criticality</th>
                <th style={{ padding: "8px 6px" }}>Payment</th>
                <th style={{ padding: "8px 6px" }}>Billing</th>
                <th style={{ padding: "8px 6px" }}>Used</th>
                <th style={{ padding: "8px 6px" }}>Remaining</th>
                <th style={{ padding: "8px 6px" }}>Health</th>
                <th style={{ padding: "8px 6px" }}>Auth</th>
                <th style={{ padding: "8px 6px" }}>Routing</th>
                <th style={{ padding: "8px 6px" }}>Owner</th>
              </tr>
            </thead>
            <tbody>
              {items.length === 0 ? (
                <tr><td colSpan={13} style={{ padding: 10, opacity: 0.8 }}>No services registered</td></tr>
              ) : items.map((it) => (
                <tr key={it.slug} style={{ borderBottom: "1px solid #111827" }}>
                  <td style={{ padding: "8px 6px", fontWeight: 700 }}>{it.name}</td>
                  <td style={{ padding: "8px 6px" }}>{it.vendor}</td>
                  <td style={{ padding: "8px 6px" }}>{it.category}</td>
                  <td style={{ padding: "8px 6px" }}>{it.enabled ? "yes" : "no"}</td>
                  <td style={{ padding: "8px 6px" }}>{it.criticality}</td>
                  <td style={{ padding: "8px 6px" }}>{it.payment_model}</td>
                  <td style={{ padding: "8px 6px" }}>{it.billing_status}</td>
                  <td style={{ padding: "8px 6px" }}>{it.used}</td>
                  <td style={{ padding: "8px 6px" }}>{it.remaining ?? ""}</td>
                  <td style={{ padding: "8px 6px" }}>{it.health_status}</td>
                  <td style={{ padding: "8px 6px" }}>{it.auth_status}</td>
                  <td style={{ padding: "8px 6px" }}>{it.routing_role}</td>
                  <td style={{ padding: "8px 6px" }}>{it.owner_department ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
