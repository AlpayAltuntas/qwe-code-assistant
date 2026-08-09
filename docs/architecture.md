# Architecture

A local, private coding assistant with two tiers, plus an optional standalone UI over Tier 2:

- **Tier 1 — Generalist**: everyday pair-programmer for any language, powered directly by a local model (Qwen3-Coder-30B-A3B via Ollama). No retrieval, no domain logic — must work standalone.
- **Tier 2 — EDI/e-invoicing specialist**: RAG-grounded (not model-memory-grounded) domain layer that auto-activates when content warrants it, via an observable, overridable router. Cleanly separable from Tier 1 so a second domain can be added later without touching the core.
- **Web UI (Phase 6)**: a standalone local web app giving Tier 2 a visual surface — invoice inspection/validation, a mapping workbench, synthetic test-data generation, and an audit/history dashboard — alongside the VS Code/Continue interface, not instead of it. Built after the Tier 2 tools exist, since it's a presentation layer over them.

Everything runs on-device. No code, invoice data, PII, tax IDs, or proprietary mappings leave the machine. The web UI's database stores only metadata and audit records — never raw invoice content — preserving that guarantee.

## Component diagram

```
┌─────────────────────────────── VS Code ───────────────────────────────┐
│                                                                          │
│   Continue.dev extension                                               │
│   ├─ Chat / Edit / Autocomplete  ──────► Ollama (OpenAI-compatible)    │
│   ├─ Router Context Provider (TS) ─────► Python Router Service         │
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
- **Router Context Provider (TS)** — runs on (almost) every message; calls the Python router; injects EDI context + a visible "why" banner when activated, nothing when not.
- **Python Router Service** — hybrid cascade classifier, fully separate from tool execution. Decides *whether* the specialist layer engages; never executes anything itself.
- **Vector store (Chroma, local/embedded)** — holds only the curated spec-document corpus (EDIFACT, UBL/PEPPOL, X12, UBL-TR, CII/ZUGFeRD spec text). Never holds real invoice payloads.
- **MCP Server (Python)** — exposes the EDI toolset as typed, allowlisted tools (`parse_edi`, `validate_with_citation`, `map_format`, `generate_synthetic_invoice`) over the Model Context Protocol.
- **Docker sandbox** — ephemeral, no network, read-only root fs, resource limits. Used for parsing untrusted payloads and executing any generated code that needs to actually run.
- **Web UI — Fastify API (TS)** — standalone backend for the web app; the only component with direct Postgres access. Calls the same Python router/MCP server that Continue calls (same loopback+token-auth contract, no privileged bypass path). Owns request validation, session handling, and translating tool results into stored audit records.
- **Web UI — React/Vite SPA** — browser frontend served by the Fastify API: invoice inspection/validation view, mapping workbench (diff-based, same review-before-apply principle as Continue), synthetic test-data generator form, and an audit/history dashboard over the Postgres metadata.
- **PostgreSQL (Docker)** — local-only, stores metadata and audit trail (citation manifests, validation verdicts, router-decision logs, mapping/generation job records). Never stores raw invoice payload content by default; a real invoice's content lives only as long as the request that processed it.

## Data flow

**Tier 1 (generalist):** editor → Continue → Ollama `/v1/chat/completions` → response streamed back. No Python service involved.

**Tier 2 (specialist):** editor message/selection → Router Context Provider → Python router (cheap cascade) → if activated: retrieve cited spec chunks from Chroma + optionally invoke an MCP tool (deterministic parse/validate/map) → results injected as context/tool output → Ollama narrates using that grounded material → response shown with citations and a router-decision banner.

**Web UI (Phase 6):** browser → Fastify API → same Python router/MCP server as Continue (parse/validate/map/generate, RAG retrieval) → Fastify writes a metadata/audit record (citations, verdict, job outcome — never raw payload content) to Postgres via Drizzle → response + citations rendered in the SPA. The web UI is a second client of the same Tier 2 backend, not a parallel implementation of it — all EDI logic still lives in the Python router/MCP server/format modules.

## Router design (hybrid cascade, cheap-first, extensible)

- **Stage 0** (near-zero cost, always runs): regex/keyword match against a per-domain lexicon (EDI: `UNH`, `BGM`, `NAD`, `EDIFACT`, `UBL`, `PEPPOL`, `ZUGFeRD`, `Factur-X`, `CII`, X12 segment patterns...). No hits → generalist path, short-circuit.
- **Stage 1** (cheap): only on weak/ambiguous Stage 0 signal — embed the message, compare against the EDI collection's top-k similarity; above threshold → activate.
- **Stage 2** (rare fallback): only if still ambiguous — one schema-constrained classification call to the same local model (`{domain, confidence, matched_signals}` enum output only, no free text, no tool access).
- Every decision is logged and surfaced in-editor; hard overrides (`/edi`, `/general`) always win.
- Adding a second domain later = registering a new `{lexicon, vectorStoreCollection, threshold, toolset}` detector — the cascade loop is domain-agnostic.

## TypeScript / Python split

**TypeScript** (editor-adjacent glue + web UI): Continue config, Router Context Provider, slash commands, the Fastify API + Drizzle/Postgres layer, the React/Vite SPA.

**Python** (ground-truth logic): ingestion pipeline, router service, format modules (EDIFACT custom tokenizer, `pyx12` for X12, `lxml`/`xmlschema`/`isoschematron` for UBL/CII/PEPPOL/UBL-TR, `pikepdf` for ZUGFeRD/Factur-X), MCP server, Docker sandbox harness.

The web UI doesn't change this split — it adds a second TypeScript-side *client* (Fastify API instead of Continue) of the same Python ground-truth logic, so EDI parsing/validation/mapping rules stay defined in exactly one place.

See `threat-model.md` for the STRIDE analysis and OWASP LLM Top 10 mapping that inform these design choices.

## Phased build plan

1. **Phase 1** — minimal generalist assistant (this repo's initial state): Ollama + Qwen3-Coder-30B-A3B, Continue.dev wired up, chat/edit/autocomplete for any language.
2. **Phase 2** — harden the generalist: repo-scale context workflows, review/test-generation commands, dev-up script.
3. **Phase 3** — RAG grounding layer: spec sourcing, ingestion pipeline, Chroma corpus, router service, Router Context Provider — separable, off by default until wired in.
4. **Phase 4** — EDI tool functions: MCP server, format modules starting with EDIFACT INVOIC ↔ UBL, expanding to X12/UBL-TR/CII/ZUGFeRD, Docker sandbox.
5. **Phase 5** — synthetic test-data generator across formats, including ZUGFeRD PDF/A-3 assembly, never seeded from real payload values without confirmation.
6. **Phase 6** — standalone web UI (`apps/web/` + `services/web-api/`): React/Vite frontend, Fastify+Drizzle API backed by a local Postgres (Docker), giving Tier 2 a visual surface (inspection, mapping workbench, test-data gen, audit dashboard) as a second client of the Phase 3/4/5 backend. Deliberately sequenced last — it's a presentation layer over tools that need to exist first.
