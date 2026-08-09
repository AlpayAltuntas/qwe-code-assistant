# Architecture

A local, private coding assistant with two tiers:

- **Tier 1 — Generalist**: everyday pair-programmer for any language, powered directly by a local model (Qwen3-Coder-30B-A3B via Ollama). No retrieval, no domain logic — must work standalone.
- **Tier 2 — EDI/e-invoicing specialist**: RAG-grounded (not model-memory-grounded) domain layer that auto-activates when content warrants it, via an observable, overridable router. Cleanly separable from Tier 1 so a second domain can be added later without touching the core.

Everything runs on-device. No code, invoice data, PII, tax IDs, or proprietary mappings leave the machine.

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
                                              └──────────────────────────┘
```

## Components

- **Ollama** — serves Qwen3-Coder-30B-A3B and a small embedding model, exposes the OpenAI-compatible `/v1` API on loopback only. Single source of inference for both tiers.
- **Continue.dev (VS Code)** — editor surface for Tier 1 (chat, inline edit, autocomplete, `@codebase` repo context) and host for Tier 2's UI (context provider + slash commands).
- **Router Context Provider (TS)** — runs on (almost) every message; calls the Python router; injects EDI context + a visible "why" banner when activated, nothing when not.
- **Python Router Service** — hybrid cascade classifier, fully separate from tool execution. Decides *whether* the specialist layer engages; never executes anything itself.
- **Vector store (Chroma, local/embedded)** — holds only the curated spec-document corpus (EDIFACT, UBL/PEPPOL, X12, UBL-TR, CII/ZUGFeRD spec text). Never holds real invoice payloads.
- **MCP Server (Python)** — exposes the EDI toolset as typed, allowlisted tools (`parse_edi`, `validate_with_citation`, `map_format`, `generate_synthetic_invoice`) over the Model Context Protocol.
- **Docker sandbox** — ephemeral, no network, read-only root fs, resource limits. Used for parsing untrusted payloads and executing any generated code that needs to actually run.

## Data flow

**Tier 1 (generalist):** editor → Continue → Ollama `/v1/chat/completions` → response streamed back. No Python service involved.

**Tier 2 (specialist):** editor message/selection → Router Context Provider → Python router (cheap cascade) → if activated: retrieve cited spec chunks from Chroma + optionally invoke an MCP tool (deterministic parse/validate/map) → results injected as context/tool output → Ollama narrates using that grounded material → response shown with citations and a router-decision banner.

## Router design (hybrid cascade, cheap-first, extensible)

- **Stage 0** (near-zero cost, always runs): regex/keyword match against a per-domain lexicon (EDI: `UNH`, `BGM`, `NAD`, `EDIFACT`, `UBL`, `PEPPOL`, `ZUGFeRD`, `Factur-X`, `CII`, X12 segment patterns...). No hits → generalist path, short-circuit.
- **Stage 1** (cheap): only on weak/ambiguous Stage 0 signal — embed the message, compare against the EDI collection's top-k similarity; above threshold → activate.
- **Stage 2** (rare fallback): only if still ambiguous — one schema-constrained classification call to the same local model (`{domain, confidence, matched_signals}` enum output only, no free text, no tool access).
- Every decision is logged and surfaced in-editor; hard overrides (`/edi`, `/general`) always win.
- Adding a second domain later = registering a new `{lexicon, vectorStoreCollection, threshold, toolset}` detector — the cascade loop is domain-agnostic.

## TypeScript / Python split

**TypeScript** (editor-adjacent glue): Continue config, Router Context Provider, slash commands.

**Python** (ground-truth logic): ingestion pipeline, router service, format modules (EDIFACT custom tokenizer, `pyx12` for X12, `lxml`/`xmlschema`/`isoschematron` for UBL/CII/PEPPOL/UBL-TR, `pikepdf` for ZUGFeRD/Factur-X), MCP server, Docker sandbox harness.

See `threat-model.md` for the STRIDE analysis and OWASP LLM Top 10 mapping that inform these design choices.

## Phased build plan

1. **Phase 1** — minimal generalist assistant (this repo's initial state): Ollama + Qwen3-Coder-30B-A3B, Continue.dev wired up, chat/edit/autocomplete for any language.
2. **Phase 2** — harden the generalist: repo-scale context workflows, review/test-generation commands, dev-up script.
3. **Phase 3** — RAG grounding layer: spec sourcing, ingestion pipeline, Chroma corpus, router service, Router Context Provider — separable, off by default until wired in.
4. **Phase 4** — EDI tool functions: MCP server, format modules starting with EDIFACT INVOIC ↔ UBL, expanding to X12/UBL-TR/CII/ZUGFeRD, Docker sandbox.
5. **Phase 5** — synthetic test-data generator across formats, including ZUGFeRD PDF/A-3 assembly, never seeded from real payload values without confirmation.
