# qwe-code-assistant

A local, private, offline coding assistant — a generalist pair-programmer for any language, with a separable EDI/e-invoicing specialist layer that engages only when relevant. Everything runs on-device via [Ollama](https://ollama.com); no code, invoice data, or PII leaves the machine.

See [`docs/architecture.md`](docs/architecture.md) for the component design and [`docs/threat-model.md`](docs/threat-model.md) for the STRIDE / OWASP-LLM-Top-10 analysis.

## Status

**Phases 1, 3, 4, 5, 6 done; Phase 2 not started.** The generalist assistant (chat/edit/autocomplete via Continue.dev + Ollama) works. The EDI/e-invoicing specialist layer is grounded via RAG (`@EDI Router` in Continue chat), has a working MCP toolset (parse/validate/map/generate across EDIFACT, UBL, CII, ZUGFeRD), and has a standalone web UI (`apps/web` + `services/web-api`) for the same capabilities outside the editor. See the Roadmap below for what's done vs. deferred within each phase.

## Prerequisites

- macOS, Apple Silicon, 32GB+ unified memory
- [Homebrew](https://brew.sh)
- Ollama and VS Code (installed via the setup script below)

## Setup

```sh
./scripts/setup.sh
```

This installs Ollama + VS Code (if missing), starts the Ollama service, pulls `qwen3-coder:30b`, and installs the Continue.dev extension.

Then, copy `apps/vscode-config/config.yaml` to `~/.continue/config.yaml` (the setup script does this too) so Continue points at the local model.

## Verifying it works

```sh
curl 127.0.0.1:11434/v1/models
```

should list `qwen3-coder:30b`. Then open this folder (or any project) in VS Code, open the Continue panel, and:

1. Ask it to explain a file.
2. Request a small inline edit/refactor.
3. Ask it to generate a unit test for a function.

All three should stream responses from the local model with no network activity — confirm via Activity Monitor's Network tab or `nettop` while chatting.

## Roadmap

1. **Phase 1** — this repo's current state: generalist assistant, any language.
2. **Phase 2** — harden the generalist: repo-scale workflows, review/test-gen commands, dev-up script.
3. **Phase 3** (done) — RAG grounding layer for EDI/e-invoicing specs (`services/router/`), invoked via `@EDI Router` in Continue chat. See `docs/architecture.md` "Invocation note" for why this is manual rather than fully automatic.
4. **Phase 4** (done) — EDI tool functions as a real MCP server (`services/mcp-server/`): parse/explain, validate-with-citation (real XSD/structural validation), EDIFACT↔UBL mapping, synthetic invoice generation. Tools are verified correct directly; invoking them via Continue+Ollama+Qwen3-coder is currently unreliable due to an upstream Ollama tool-calling bug — see `docs/architecture.md` Phase 4 note.
5. **Phase 5** (done, ZUGFeRD/Factur-X scope) — `parse_edi`, `validate_with_citation`, and `generate_synthetic_invoice` gained `cii`/`zugferd` formats, built on the `factur-x` library (real CII XSD validation + PDF/A-3 assembly). Router corpus grew by 1,091 chunks. X12/UBL-TR remain future work.
6. **Phase 6** (first pass done) — standalone web UI: React/Vite frontend + Fastify/Drizzle API + PostgreSQL (an existing local Postgres.app instance, not the originally-planned Docker container — see `docs/architecture.md`), giving Tier 2 a visual surface alongside VS Code (`apps/web/`, `services/web-api/`). Shipped: test-data generation, inspection/validation, and an interactive EDIFACT→UBL field-mapping tool with saved/reusable mapping profiles. Deferred: audit/history dashboard.

## License

Apache-2.0 — see [`LICENSE`](LICENSE).
