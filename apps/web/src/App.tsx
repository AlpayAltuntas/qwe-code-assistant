import { useState } from "react";
import { GenerateTab } from "./components/GenerateTab";
import { InspectTab } from "./components/InspectTab";
import { MappingTab } from "./components/MappingTab";
import "./App.css";

type Tab = "generate" | "inspect" | "mapping";

function App() {
  const [tab, setTab] = useState<Tab>("generate");

  return (
    <div className="app">
      <header className="app-header">
        <h1>EDI / e-invoicing toolkit</h1>
        <p className="subtitle">
          A visual surface over the same parse/validate/generate/map tools Continue calls — see{" "}
          <code>docs/architecture.md</code>.
        </p>
      </header>

      <nav className="tabs">
        <button className={tab === "generate" ? "active" : ""} onClick={() => setTab("generate")}>
          Generate
        </button>
        <button className={tab === "inspect" ? "active" : ""} onClick={() => setTab("inspect")}>
          Inspect &amp; Validate
        </button>
        <button className={tab === "mapping" ? "active" : ""} onClick={() => setTab("mapping")}>
          Mapping
        </button>
      </nav>

      <main>
        {tab === "generate" && <GenerateTab />}
        {tab === "inspect" && <InspectTab />}
        {tab === "mapping" && <MappingTab />}
      </main>
    </div>
  );
}

export default App;
