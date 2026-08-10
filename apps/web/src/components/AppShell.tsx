import { FilePlus2, FileSearch, Layers, Sparkles, Waypoints } from "lucide-react";
import type { ReactNode } from "react";

export type Tab = "generate" | "inspect" | "mapping" | "create";

const NAV_ITEMS: { tab: Tab; label: string; icon: ReactNode }[] = [
  { tab: "generate", label: "Generate", icon: <Sparkles size={16} /> },
  { tab: "inspect", label: "Inspect & Validate", icon: <FileSearch size={16} /> },
  { tab: "mapping", label: "Mapping", icon: <Waypoints size={16} /> },
  { tab: "create", label: "Create", icon: <FilePlus2 size={16} /> },
];

interface AppShellProps {
  activeTab: Tab;
  onTabChange: (tab: Tab) => void;
  apiConnected: boolean | null;
  children: ReactNode;
}

export function AppShell({ activeTab, onTabChange, apiConnected, children }: AppShellProps) {
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <span className="brand-mark">
            <Layers size={17} strokeWidth={2.25} />
          </span>
          <div>
            <div className="brand-title">EDI Toolkit</div>
            <div className="brand-subtitle">local &amp; private</div>
          </div>
        </div>

        <nav className="sidebar-nav">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.tab}
              className={`sidebar-nav-item ${activeTab === item.tab ? "active" : ""}`}
              onClick={() => onTabChange(item.tab)}
              type="button"
            >
              {item.icon}
              {item.label}
            </button>
          ))}
        </nav>

        <div className="sidebar-footer">
          <span
            className={`status-dot ${
              apiConnected === null ? "status-dot-pending" : apiConnected ? "status-dot-ok" : "status-dot-off"
            }`}
          />
          {apiConnected === null ? "Checking API…" : apiConnected ? "API connected" : "API unreachable"}
        </div>
      </aside>

      <main className="main">{children}</main>
    </div>
  );
}
