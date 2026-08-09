# Web UI (Phase 6)

React + Vite SPA giving the EDI/e-invoicing specialist layer a standalone visual surface, alongside (not instead of) the VS Code/Continue interface. Talks only to `services/web-api` — never to Ollama, the router, or the MCP server directly.

## Setup

```sh
npm install
cp .env.example .env   # VITE_API_BASE_URL, defaults to http://127.0.0.1:8788
npm run dev            # http://127.0.0.1:5173
```

Requires `services/web-api` running (see its README) — the SPA has no functionality of its own without it.

## Tabs

- **Generate** — form-driven synthetic test-invoice generation (EDIFACT, UBL, CII, ZUGFeRD/Factur-X) with download.
- **Inspect & Validate** — paste or upload a message, see it parsed segment-by-segment / element-by-element, get a deterministic validation verdict with findings and spec citations.
- **Mapping** — build an EDIFACT → UBL field mapping interactively from a sample document (per-target-field dropdowns, not a drag-line canvas — deliberately simpler), save it as a named reusable profile, and apply it to other documents with the same segment shape.

Audit/history dashboard is a follow-up pass — the underlying data (`tool_invocations`) is already being written by every API call, just not surfaced in the UI yet.

Loopback-only dev server (`vite.config.ts` binds `127.0.0.1:5173`) — see `docs/threat-model.md` S1.
