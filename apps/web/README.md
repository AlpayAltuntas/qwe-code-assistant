# Web UI (Phase 6)

React + Vite SPA giving the EDI/e-invoicing specialist layer a standalone visual surface, alongside (not instead of) the VS Code/Continue interface. Talks only to `services/web-api` — never to Ollama, the router, or the MCP server directly.

## Setup

```sh
npm install
cp .env.example .env   # VITE_API_BASE_URL, defaults to http://127.0.0.1:8788
npm run dev            # http://127.0.0.1:5173
```

Requires `services/web-api` running (see its README) — the SPA has no functionality of its own without it.

## Design

Sidebar-navigated (not tabs) over a small internal design system in
`src/components/ui` (Button, Card, Badge, Alert, CodeBlock with
copy-to-clipboard, Field variants), built on CSS custom-property tokens
(`src/index.css`) with real light/dark theming — clean/technical aesthetic,
one accent color, monospace for EDI/XML content.

## Pages

- **Generate** — form-driven synthetic test-invoice generation (EDIFACT, UBL, CII, ZUGFeRD/Factur-X) with download.
- **Inspect & Validate** — drag-drop or paste a message, see it parsed segment-by-segment / element-by-element, get a deterministic validation verdict with findings and spec citations.
- **Mapping** — build a field mapping interactively from a sample document, any of EDIFACT/UBL/CII/ZUGFeRD to any other: ~30 header fields (grouped: Invoice/Supplier/Customer/Payment/Totals & tax) and ~10 line-item fields, each mapped to either a source field (addressed by tag+occurrence, not raw position — one address shape for every source format) or a typed-in constant value. Save as a named reusable profile, then apply it to *any* document in that source format — the line-item mapping is a template applied once per line-item group the target document actually has, so a profile built from a 2-line sample works unchanged on a 30-line invoice.
- **Create** — build a document from scratch by typing field values directly, no source document required: the same header/line-item field catalog as Mapping, plus repeatable line-item rows and a target format picker. Useful when there's no existing document to map from at all.

Audit/history dashboard is a follow-up pass — the underlying data (`tool_invocations`) is already being written by every API call, just not surfaced in the UI yet.

Loopback-only dev server (`vite.config.ts` binds `127.0.0.1:5173`) — see `docs/threat-model.md` S1.
