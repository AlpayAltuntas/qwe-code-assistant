# Architecture

A local, private coding assistant with two tiers, plus an optional standalone UI over Tier 2:

- **Tier 1 — Generalist**: everyday pair-programmer for any language, powered directly by a local model (Qwen3-Coder-30B-A3B via Ollama). No retrieval, no domain logic — must work standalone.
- **Tier 2 — EDI/e-invoicing specialist**: RAG-grounded (not model-memory-grounded) domain layer, invoked via `@EDI Router` in Continue chat, backed by an observable, overridable classifier. Cleanly separable from Tier 1 so a second domain can be added later without touching the core. (Originally designed for fully silent auto-activation on every message — see the note under "Router design" for why that's not currently achievable and what was built instead.)
- **Web UI (Phase 6)**: a standalone local web app giving Tier 2 a visual surface — invoice inspection/validation, a mapping workbench, synthetic test-data generation, and an audit/history dashboard — alongside the VS Code/Continue interface, not instead of it. Built after the Tier 2 tools exist, since it's a presentation layer over them.

Everything runs on-device. No code, invoice data, PII, tax IDs, or proprietary mappings leave the machine. The web UI's database stores only metadata and audit records — never raw invoice content — preserving that guarantee.

## Component diagram

```
┌─────────────────────────────── VS Code ───────────────────────────────┐
│                                                                          │
│   Continue.dev extension                                               │
│   ├─ Chat / Edit / Autocomplete  ──────► Ollama (OpenAI-compatible)    │
│   ├─ "@EDI Router" context provider ───► Python Router Service         │
│   │  (built-in http provider, config.yaml — see note below)           │
│   └─ Slash commands (/edi-validate,                                    │
│      /edi-map, /edi-testdata)     ─────► Python MCP Server             │
│                                                                          │
└──────────────────────────────────────────────────────────────────────┘
                 │                                    │
                 ▼                                    ▼
        ┌────────────────┐                 ┌──────────────────────────┐
        │  Ollama daemon  │                 │  Python services (local) │
        │  127.0.0.1:11434│                 │  loopback-only, token-auth│
        │  Qwen3-Coder-30B│                 │                           │
        │  + embed model  │                 │  ┌─────────────────────┐ │
        └────────────────┘                 │  │ Router (hybrid       │ │
                 ▲                          │  │ cascade)              │ │
                 │ embeddings                │  └─────────┬───────────┘ │
                 │                          │            │             │
        ┌────────┴─────────┐                │  ┌─────────▼───────────┐ │
        │  Vector store      │◄───ingest────┤  │ EDI Tool Modules     │ │
        │  (Chroma, local)   │   pipeline    │  │ parse / validate /   │ │
        │  spec corpus only  │               │  │ map / generate       │ │
        └────────────────────┘               │  └─────────┬───────────┘ │
                                              │            │             │
                                              │  ┌─────────▼───────────┐ │
                                              │  │ Docker sandbox       │ │
                                              │  │ (untrusted parsing / │ │
                                              │  │ generated-code exec) │ │
                                              │  └──────────────────────┘ │
                                              └───────────▲──────────────┘
                                                           │ same MCP tool calls
                                                           │ (loopback, token-auth)
┌──────────────────────── Standalone Web UI (Phase 6) ────┴──────────────────┐
│                                                                              │
│   Browser (React + Vite SPA) ──────► Fastify API (TS)                      │
│   inspect / mapping workbench /      ├─ calls Python router + MCP server    │
│   test-data gen / audit dashboard    │  (loopback, token-auth, same as       │
│                                       │   Continue's calls)                  │
│                                       └─ Drizzle ORM ──► PostgreSQL (Docker) │
│                                          metadata & audit only —             │
│                                          citations, verdicts, router         │
│                                          decisions, job records.             │
│                                          Never raw invoice content.          │
└──────────────────────────────────────────────────────────────────────────┘
```

## Components

- **Ollama** — serves Qwen3-Coder-30B-A3B and a small embedding model, exposes the OpenAI-compatible `/v1` API on loopback only. Single source of inference for both tiers.
- **Continue.dev (VS Code)** — editor surface for Tier 1 (chat, inline edit, autocomplete, `@codebase` repo context) and host for Tier 2's UI (context provider + slash commands).
- **"@EDI Router" context provider** — Continue's built-in `http` context provider (declared in `apps/vscode-config/config.yaml`, no custom code), invoked by typing `@EDI Router` in a chat message. Calls the Python router's `/context` endpoint; injects an activation banner + cited spec chunks as context items when the router decides the message is in-domain, an empty result when not.
- **Python Router Service** — hybrid cascade classifier, fully separate from tool execution. Decides *whether* the specialist layer engages; never executes anything itself.
- **Vector store (Chroma, local/embedded)** — holds only the curated spec-document corpus (EDIFACT, UBL/PEPPOL, X12, UBL-TR, CII/ZUGFeRD spec text). Never holds real invoice payloads.
- **MCP Server (Python, `services/mcp-server`)** — exposes the EDI toolset as typed, allowlisted tools (`parse_edi`, `validate_with_citation`, `map_format`, `generate_synthetic_invoice`) over the real Model Context Protocol (stdio transport, launched by Continue via `mcpServers:` in config.yaml). No generic exec tool exists — each tool is a fixed function signature. Currently EDIFACT INVOIC ↔ UBL Invoice only.
- **Docker sandbox** — planned, not yet built. Current mitigation for untrusted-payload parsing (docs/threat-model.md D1/E1) is in-process: hard input-size caps, wall-clock parse timeouts, `defusedxml` for all XML parsing (including the tree actually used for XSD validation, not just a pre-check).
- **Web UI — Fastify API (TS)** — standalone backend for the web app; the only component with direct Postgres access. Calls the same Python router/MCP server that Continue calls (same loopback+token-auth contract, no privileged bypass path). Owns request validation, session handling, and translating tool results into stored audit records.
- **Web UI — React/Vite SPA** — browser frontend served by the Fastify API: invoice inspection/validation view, mapping workbench (diff-based, same review-before-apply principle as Continue), synthetic test-data generator form, and an audit/history dashboard over the Postgres metadata.
- **PostgreSQL (Docker)** — local-only, stores metadata and audit trail (citation manifests, validation verdicts, router-decision logs, mapping/generation job records). Never stores raw invoice payload content by default; a real invoice's content lives only as long as the request that processed it.

## Data flow

**Tier 1 (generalist):** editor → Continue → Ollama `/v1/chat/completions` → response streamed back. No Python service involved.

**Tier 2 (specialist):** user types `@EDI Router` + their message → Continue's http context provider POSTs `{fullInput, ...}` to the router's `/context` endpoint → Python router runs the cheap cascade → if activated: retrieve cited spec chunks from Chroma + optionally invoke an MCP tool (deterministic parse/validate/map) → results returned as context items (banner + citations) → Ollama narrates using that grounded material → response shown with citations and a router-decision banner. If the router decides the message isn't in-domain, it returns an empty list and nothing is injected.

**Web UI (Phase 6):** browser → Fastify API → same Python router/MCP server as Continue (parse/validate/map/generate, RAG retrieval) → Fastify writes a metadata/audit record (citations, verdict, job outcome — never raw payload content) to Postgres via Drizzle → response + citations rendered in the SPA. The web UI is a second client of the same Tier 2 backend, not a parallel implementation of it — all EDI logic still lives in the Python router/MCP server/format modules.

## Router design (hybrid cascade, cheap-first, extensible)

- **Stage 0** (near-zero cost, always runs): regex/keyword match against a per-domain lexicon (EDI: `UNH`, `BGM`, `NAD`, `EDIFACT`, `UBL`, `PEPPOL`, `ZUGFeRD`, `Factur-X`, `CII`, X12 segment patterns...). No hits → generalist path, short-circuit.
- **Stage 1** (cheap): only on weak/ambiguous Stage 0 signal — embed the message, compare against the EDI collection's top-k similarity; above threshold → activate.
- **Stage 2** (rare fallback): only if still ambiguous — one schema-constrained classification call to the same local model (`{domain, confidence, matched_signals}` enum output only, no free text, no tool access).
- Every decision is logged and surfaced in-editor; hard overrides (a message starting `/edi` or `/general`) always win over the cascade's own decision.
- Adding a second domain later = registering a new `{lexicon, vectorStoreCollection, threshold, toolset}` detector — the cascade loop is domain-agnostic.

**Invocation note — why this isn't fully silent.** The original design called for the router to run on every message with zero user action. In practice, two mechanisms were tried and both fell short in Continue's current (v2.0) VS Code extension:

1. A custom `CustomContextProvider` registered via `config.ts`'s `modifyConfig` hook, pushed to run on every message via `experimental.defaultContext` — per Continue's own type definitions this should auto-inject context on every message. It never fired: Continue's newer YAML "Hub" config resolution doesn't appear to consult `config.ts` at all (confirmed by inspecting session transcripts — zero context items were ever attached, and no "Continue" output channel or log file recorded any config.ts execution).
2. Declaring the router as a built-in `http` context provider directly in `config.yaml`'s `context:` list (the officially-recommended replacement for custom providers). This *is* the supported, working integration — but entries in `context:` are only available for **manual `@`-invocation**, not automatically attached to every message; there is no discovered config-level "always on" flag for this provider type.

What ships today: the classifier, retrieval, citations, logging, and override logic all work exactly as designed and are verified end-to-end — the only gap is that the user types `@EDI Router` once per message instead of the layer engaging invisibly. If Continue adds a supported always-on hook for context providers, switching over is a config.yaml change, not a redesign.

## TypeScript / Python split

**TypeScript** (editor-adjacent glue + web UI): Continue config (the router integration is declarative YAML, no custom TS code), slash commands, the Fastify API + Drizzle/Postgres layer, the React/Vite SPA.

**Python** (ground-truth logic): ingestion pipeline, router service, format modules (EDIFACT custom tokenizer + structural validator, `xmlschema` for UBL against the real OASIS XSD chain; `pyx12` for X12 and `pikepdf` for ZUGFeRD/Factur-X remain future work), MCP server (`services/mcp-server`, real MCP protocol via the `mcp` SDK), Docker sandbox harness (deferred — see Phase 4 note below).

The web UI doesn't change this split — it adds a second TypeScript-side *client* (Fastify API instead of Continue) of the same Python ground-truth logic, so EDI parsing/validation/mapping rules stay defined in exactly one place.

See `threat-model.md` for the STRIDE analysis and OWASP LLM Top 10 mapping that inform these design choices.

## Phased build plan

1. **Phase 1** — minimal generalist assistant (this repo's initial state): Ollama + Qwen3-Coder-30B-A3B, Continue.dev wired up, chat/edit/autocomplete for any language.
2. **Phase 2** — harden the generalist: repo-scale context workflows, review/test-generation commands, dev-up script.
3. **Phase 3** (done) — RAG grounding layer: spec sourcing (EDIFACT D01B INVOIC + UBL 2.1 Invoice/CommonAggregateComponents/CommonBasicComponents, 3,920 chunks), ingestion pipeline, Chroma corpus, hybrid-cascade router service, `@EDI Router` context provider — separable, invoked manually per-message (see "Invocation note" above).
4. **Phase 4** (done, with a known caveat) — EDI tool functions as a real MCP server (`services/mcp-server`): `parse_edi`, `validate_with_citation` (real XSD schema validation for UBL, structural rules for EDIFACT — deterministic, never the model), `map_format` (EDIFACT INVOIC → UBL Invoice, common field correspondences), `generate_synthetic_invoice`. Scope for this pass: EDIFACT INVOIC ↔ UBL Invoice only (matches the Phase 3 corpus); X12/UBL-TR/CII/ZUGFeRD remain future work. No Docker sandbox yet — hardened in-process instead (input size caps, parse timeouts, `defusedxml` end-to-end so the XSD-validation parse itself is covered, not just a pre-check). All four tools verified correct via direct MCP protocol calls (list_tools + call_tool). **Known gap**: invoking them through Continue+Ollama+Qwen3-coder is currently unreliable — Ollama's tool-call parser for this model has documented bugs (malformed `<function=...>` output, occasionally answering directly instead of calling the tool) as of mid-2026. Not a bug in this codebase; revisit when Ollama ships a fix, or call the tools directly (`uv run` / MCP client) in the meantime.
5. **Phase 5** — expand synthetic test-data generation to X12/UBL-TR/CII/ZUGFeRD (PDF/A-3 assembly), and the corresponding format modules for `parse_edi`/`validate_with_citation`/`map_format`. Never seeded from real payload values without confirmation.
6. **Phase 6** — standalone web UI (`apps/web/` + `services/web-api/`): React/Vite frontend, Fastify+Drizzle API backed by a local Postgres (Docker), giving Tier 2 a visual surface (inspection, mapping workbench, test-data gen, audit dashboard) as a second client of the Phase 3/4/5 backend. Deliberately sequenced last — it's a presentation layer over tools that need to exist first.
