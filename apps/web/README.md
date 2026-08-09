# Web UI (Phase 6 placeholder)

React + Vite SPA giving the EDI/e-invoicing specialist layer a standalone visual surface, alongside (not instead of) the VS Code/Continue interface:

- Invoice inspection/validation — segment-by-segment breakdown, verdict, spec citations
- Mapping workbench — diff-based review of generated format-to-format mapping code
- Synthetic test-data generator — form-driven invoice generation across formats
- Audit/history dashboard — browsable log of past validations/mappings, backed by `services/web-api`

Talks only to `services/web-api` (Fastify). Never calls Ollama, the router, or the MCP server directly.

Not implemented yet — sequenced after Phases 3–5 since this is a presentation layer over tools that need to exist first. See `docs/architecture.md`.
