import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import ArchitecturePage from "./ArchitecturePage";
import ExternalServicesPage from "./ExternalServicesPage";

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "260px 1fr", height: "100vh", background: "#070b12", color: "#e5e7eb" }}>
      <aside style={{ borderRight: "1px solid #111827", padding: 14 }}>
        <div style={{ fontWeight: 800 }}>Staff UI</div>
        <div style={{ opacity: 0.7, fontSize: 12, marginTop: 6 }}>Architecture + status</div>
        <nav style={{ marginTop: 18, display: "grid", gap: 8 }}>
          <Link style={{ color: "#e5e7eb", textDecoration: "none" }} to="/architecture">Architecture</Link>
          <Link style={{ color: "#e5e7eb", textDecoration: "none" }} to="/operations/external-services">External Services</Link>
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
          <Route path="/operations/external-services" element={<ExternalServicesPage />} />
        </Routes>
      </Shell>
    </BrowserRouter>
  );
}
