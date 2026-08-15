import { FilePlus2, FileSearch, Layers, Monitor, Moon, Sparkles, Sun, Waypoints } from "lucide-react";
import type { ReactNode } from "react";
import { type ThemePreference, useTheme } from "../useTheme";

export type Tab = "generate" | "inspect" | "mapping" | "create";

const NAV_ITEMS: { tab: Tab; label: string; icon: ReactNode }[] = [
  { tab: "generate", label: "Generate", icon: <Sparkles size={16} /> },
  { tab: "inspect", label: "Inspect & Validate", icon: <FileSearch size={16} /> },
  { tab: "mapping", label: "Mapping", icon: <Waypoints size={16} /> },
  { tab: "create", label: "Create", icon: <FilePlus2 size={16} /> },
];

const THEME_OPTIONS: { pref: ThemePreference; icon: ReactNode; label: string }[] = [
  { pref: "light", icon: <Sun size={13} />, label: "Light theme" },
  { pref: "system", icon: <Monitor size={13} />, label: "Match system theme" },
  { pref: "dark", icon: <Moon size={13} />, label: "Dark theme" },
];

interface AppShellProps {
  activeTab: Tab;
  onTabChange: (tab: Tab) => void;
  apiConnected: boolean | null;
  children: ReactNode;
}

export function AppShell({ activeTab, onTabChange, apiConnected, children }: AppShellProps) {
  const [theme, setTheme] = useTheme();

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

        <div className="sidebar-bottom">
          <div className="mode-toggle mode-toggle-icon theme-toggle">
            {THEME_OPTIONS.map((o) => (
              <button
                key={o.pref}
                type="button"
                className={theme === o.pref ? "active" : ""}
                onClick={() => setTheme(o.pref)}
                title={o.label}
                aria-label={o.label}
              >
                {o.icon}
              </button>
            ))}
          </div>

          <div className="sidebar-footer">
            <span
              className={`status-dot ${
                apiConnected === null ? "status-dot-pending" : apiConnected ? "status-dot-ok" : "status-dot-off"
              }`}
            />
            {apiConnected === null ? "Checking API…" : apiConnected ? "API connected" : "API unreachable"}
          </div>
        </div>
      </aside>

      <main className="main">{children}</main>
    </div>
  );
}
