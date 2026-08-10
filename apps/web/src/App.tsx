import { useEffect, useState } from "react";
import { checkHealth } from "./api";
import { AppShell, type Tab } from "./components/AppShell";
import { PageHeader } from "./components/PageHeader";
import { CreateTab } from "./components/CreateTab";
import { GenerateTab } from "./components/GenerateTab";
import { InspectTab } from "./components/InspectTab";
import { MappingTab } from "./components/MappingTab";
import "./App.css";

const PAGE_COPY: Record<Tab, { title: string; description: string }> = {
  generate: {
    title: "Generate",
    description:
      "Create a synthetic, entirely fictional test invoice — never derived from real customer data.",
  },
  inspect: {
    title: "Inspect & Validate",
    description:
      "Paste or upload a message to see it explained segment-by-segment and validated against real spec rules.",
  },
  mapping: {
    title: "Mapping",
    description:
      "Build a reusable field mapping from a sample document, then apply it to others — any of EDIFACT/UBL/CII/ZUGFeRD to any other.",
  },
  create: {
    title: "Create",
    description:
      "Build a document by entering field values directly — no source document required.",
  },
};

function App() {
  const [tab, setTab] = useState<Tab>("generate");
  const [apiConnected, setApiConnected] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function poll() {
      const ok = await checkHealth();
      if (!cancelled) setApiConnected(ok);
    }
    poll();
    const interval = setInterval(poll, 15000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  const copy = PAGE_COPY[tab];

  return (
    <AppShell activeTab={tab} onTabChange={setTab} apiConnected={apiConnected}>
      <div className="page">
        <PageHeader title={copy.title} description={copy.description} />
        {tab === "generate" && <GenerateTab />}
        {tab === "inspect" && <InspectTab />}
        {tab === "mapping" && <MappingTab />}
        {tab === "create" && <CreateTab />}
      </div>
    </AppShell>
  );
}

export default App;
