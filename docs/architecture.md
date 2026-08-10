# Architecture

A local, private coding assistant with two tiers, plus an optional standalone UI over Tier 2:

- **Tier 1 — Generalist**: everyday pair-programmer for any language, powered directly by a local model (Qwen3-Coder-30B-A3B via Ollama). No retrieval, no domain logic — must work standalone.
- **Tier 2 — EDI/e-invoicing specialist**: RAG-grounded (not model-memory-grounded) domain layer, invoked via `@EDI Router` in Continue chat, backed by an observable, overridable classifier. Cleanly separable from Tier 1 so a second domain can be added later without touching the core. (Originally designed for fully silent auto-activation on every message — see the note under "Router design" for why that's not currently achievable and what was built instead.)
- **Web UI (Phase 6, first pass done)**: a standalone local web app giving Tier 2 a visual surface, alongside the VS Code/Continue interface, not instead of it. Shipped so far: synthetic test-data generation, inspection/validation, and an interactive EDIFACT→UBL field-mapping tool (build a reusable mapping from a sample document, apply it to others). An audit/history dashboard remains a follow-up pass — see the Phase 6 note below.

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
                                                           │ spawns as a stdio
                                                           │ subprocess, same as
                                                           │ Continue's mcpServers:
┌──────────────────────── Standalone Web UI (Phase 6) ────┴──────────────────┐
│                                                                              │
│   Browser (React + Vite SPA) ──────► Fastify API (TS)                      │
│   Generate / Inspect &amp; Validate     ├─ spawns services/mcp-server per call │
│   (mapping workbench + audit          │  via @modelcontextprotocol/sdk       │
│    dashboard: follow-up pass)         │  (MCP server calls the router's      │
│                                       │  /retrieve over HTTP internally,     │
│                                       │  for citations — same as Phase 5)    │
│                                       └─ Drizzle ORM ──► PostgreSQL          │
│                                          (existing local Postgres.app       │
│                                          instance, not Docker — see note)   │
│                                          metadata & audit only —             │
│                                          tool name, format, verdict,         │
│                                          summary. Never raw invoice content. │
└──────────────────────────────────────────────────────────────────────────┘
```

## Components

- **Ollama** — serves Qwen3-Coder-30B-A3B and a small embedding model, exposes the OpenAI-compatible `/v1` API on loopback only. Single source of inference for both tiers.
- **Continue.dev (VS Code)** — editor surface for Tier 1 (chat, inline edit, autocomplete, `@codebase` repo context) and host for Tier 2's UI (context provider + slash commands).
- **"@EDI Router" context provider** — Continue's built-in `http` context provider (declared in `apps/vscode-config/config.yaml`, no custom code), invoked by typing `@EDI Router` in a chat message. Calls the Python router's `/context` endpoint; injects an activation banner + cited spec chunks as context items when the router decides the message is in-domain, an empty result when not.
- **Python Router Service** — hybrid cascade classifier, fully separate from tool execution. Decides *whether* the specialist layer engages; never executes anything itself.
- **Vector store (Chroma, local/embedded)** — holds only the curated spec-document corpus (EDIFACT, UBL/PEPPOL, X12, UBL-TR, CII/ZUGFeRD spec text). Never holds real invoice payloads.
- **MCP Server (Python, `services/mcp-server`)** — exposes the EDI toolset as typed, allowlisted tools (`parse_edi`, `validate_with_citation`, `map_format`, `describe_mapping_source_fields`, `apply_mapping_profile`, `build_document`, `generate_synthetic_invoice`) over the real Model Context Protocol (stdio transport, launched by Continue via `mcpServers:` in config.yaml, and separately spawned by the web UI's Fastify API per call — see below). No generic exec tool exists — each tool is a fixed function signature. `parse_edi`/`validate_with_citation`/`generate_synthetic_invoice` support EDIFACT INVOIC, UBL Invoice, CII (raw XML), and ZUGFeRD/Factur-X (PDF/A-3 with embedded CII, via the `factur-x` library). `map_format` stays EDIFACT→UBL only (the original fixed correspondence table). `apply_mapping_profile` is its any-format-to-any-format sibling: **EDIFACT, UBL, and CII/ZUGFeRD can each be the source or the target**, in any combination — a user builds field mappings themselves (via the web UI's Mapping tab) instead of relying on a hardcoded table. All three source formats convert into one shared tree-node intermediate representation (`ir.py`) before anything gets addressed — EDIFACT's segment/element/component shape becomes real tree nesting via synthesized position tags (`edifact.to_ir`; a segment's element/component index becomes a child node tagged `"e<i>.c<j>"`, and EDIFACT's line items — really a *sibling range* between LIN markers, not true nesting — get wrapped into a synthetic container node), while UBL/CII XML converts almost 1:1 (`xmlmap.to_ir`). The result: every source field, regardless of format, is addressed the same way — `{parent_tag, tag, occurrence}` — and the field-listing/value-extraction logic (`ir.build_scope`/`flatten_fields`/`extract_by_ref`) is implemented exactly once rather than once per format. A line-item mapping is a *template* applied once per detected line-item group (EDIFACT: LIN-delimited; UBL: `cac:InvoiceLine`; CII: `ram:IncludedSupplyChainTradeLineItem`) — so a saved profile generalizes across documents with different line counts, not just the exact shape of the sample it was built from; verified end-to-end (both through the real MCP protocol and the actual HTTP API) with a mapping built from a 2-line sample correctly producing 2/7/1 output lines from documents with those counts. A target field's source can also be a constant value instead of a source field. Not every canonical field has a home in every target format (EDIFACT's simplified D01B builder has no address fields, for instance) — each target builder reports what it had to drop rather than silently discarding it. X12 and UBL-TR are out of scope for mapping (as for everything else in this service) since no parser exists for either format yet. `build_document` is `apply_mapping_profile`'s sibling for the no-source-document case: a caller supplies canonical header/line field values directly (no field mappings, no document to resolve them from) and gets the same target-format output — it shares `mapping.py`'s format-agnostic `build_target` step with `apply_mapping_profile`, so field support/defaulting/dropped-field reporting behave identically either way.
- **Docker sandbox** — planned, not yet built. Current mitigation for untrusted-payload parsing (docs/threat-model.md D1/E1) is in-process: hard input-size caps, wall-clock parse timeouts, `defusedxml` for all XML parsing (including the tree actually used for XSD validation, not just a pre-check).
- **Web UI — Fastify API (TS, `services/web-api`)** — standalone backend for the web app; the only component with direct Postgres access. A second *client* of `services/mcp-server`, not a parallel implementation — spawns it as a stdio subprocess per tool call via `@modelcontextprotocol/sdk`, exactly like Continue's `mcpServers:` does (docs/threat-model.md E3: no privileged bypass path). Owns request validation (zod) and translating tool results into stored audit records. Bound to `127.0.0.1`, strict CORS allowlist (no wildcard — S3).
- **Web UI — React/Vite SPA (`apps/web`)** — browser frontend, talks only to the Fastify API. A sidebar-navigated app (not tabs) over a small internal design system (`src/components/ui`: Button, Card, Badge, Alert, CodeBlock, Field variants) built on token-based light/dark theming. Shipped: a Generate tab (calls `generate_synthetic_invoice`, with download); an Inspect & Validate tab (calls `parse_edi` + `validate_with_citation`, showing the segment breakdown, verdict, findings, and citations); a Mapping tab — pick any source/target format pair (EDIFACT/UBL/CII/ZUGFeRD, PDF upload for ZUGFeRD), load a sample document's fields, map ~30 header fields (grouped: Invoice/Supplier/Customer/Payment/Totals & tax) and ~10 line-item fields each to either a source field or a constant value, save as a named reusable mapping profile, then apply it to any document in that source format regardless of line count; and a Create tab — the same header/line-item field catalog, but typed in directly with repeatable line-item rows and a target format picker, for building a document with no source document to map from at all (calls `build_document`). Audit/history dashboard is a follow-up pass.
- **PostgreSQL** — local-only, two tables with deliberately different access grants for the same DB role (`qwe_web_api`): `tool_invocations` (audit trail — tool name, format, verdict, short summary; `INSERT`+`SELECT` only, no `UPDATE`/`DELETE`, verified at the database level — see R3) and `mapping_profiles` (user-authored, editable config — full CRUD, since restricting it wouldn't protect anything and would just break renaming/deleting a saved mapping). Neither table stores raw invoice payload content — `mapping_profiles` stores tag+occurrence coordinates into a sample's parsed structure (or literal constant values the user typed), never the sample document's own field values. Runs on an existing local Postgres.app instance rather than a fresh Docker container, per a build-time decision documented in the Phase 6 note below — not the Docker-isolated design originally sketched.

## Data flow

**Tier 1 (generalist):** editor → Continue → Ollama `/v1/chat/completions` → response streamed back. No Python service involved.

**Tier 2 (specialist):** user types `@EDI Router` + their message → Continue's http context provider POSTs `{fullInput, ...}` to the router's `/context` endpoint → Python router runs the cheap cascade → if activated: retrieve cited spec chunks from Chroma + optionally invoke an MCP tool (deterministic parse/validate/map) → results returned as context items (banner + citations) → Ollama narrates using that grounded material → response shown with citations and a router-decision banner. If the router decides the message isn't in-domain, it returns an empty list and nothing is injected.

**Web UI (Phase 6):** browser → Fastify API → spawns `services/mcp-server` as a stdio subprocess (same MCP tool contract Continue uses) → for `validate_with_citation`, that Python process itself calls the router's `/retrieve` over HTTP, same as it does for Continue → results returned up through Fastify, which writes a metadata/audit record (tool, format, verdict, summary — never raw payload content) to Postgres via Drizzle → response + citations rendered in the SPA. The web UI is a second client of the same Tier 2 backend, not a parallel implementation of it — all EDI logic still lives in the Python router/MCP server/format modules.

**Phase 6 build note — Postgres.** The original design called for Postgres in its own Docker container. Mid-build, an already-running native Postgres.app instance was found on this machine (the same stray process flagged during Phase 1 verification). Rather than standing up a second, isolated Postgres, Phase 6 reuses it: a dedicated low-privilege role (`qwe_web_api`) and database (`qwe_web_ui`) were created inside it, with `INSERT`+`SELECT`-only grants on the audit table (no superuser access, no `UPDATE`/`DELETE`) — verified by a live test that a `DELETE` from that role is actually rejected by Postgres, not just discouraged by convention. This trades the stronger process-level isolation Docker would have given the database for simplicity — worth revisiting if Phase 6 grows to store anything more sensitive than tool-invocation metadata.

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
5. **Phase 5** (done, ZUGFeRD/Factur-X scope) — added `cii`/`zugferd` as formats across `parse_edi`, `validate_with_citation`, and `generate_synthetic_invoice` (not `map_format` — scoped out this pass). Built on the `factur-x` library (BSD-licensed) rather than hand-resolving UN/CEFACT's full CII codelist schema tree (dozens of files) — it bundles a working, real schema set and handles PDF/A-3 + XMP metadata assembly. `generate_synthetic_invoice(format="zugferd")` produces an actual PDF/A-3 with a schema-valid CII XML embedded (correct `AFRelationship`); the PDF's visual layer is a blank placeholder page, not a rendered invoice — the XML is the authoritative content, consistent with this being a test-fixture generator, not a document-design tool. The Phase 3 router corpus grew by 1,091 chunks from a real annotated CII schema (only available inside the `factur-x` PyPI sdist, not a stable public URL — `router-ingest fetch` downloads the sdist and extracts just that file). Found and fixed a real bug along the way: the Phase 4 parse-timeout mechanism used `signal.alarm`, which only works on a process's main thread — it crashed the instant a real MCP tool call exercised it, since MCP dispatches tool calls on a worker thread. Replaced with a `ThreadPoolExecutor`-based timeout. X12 and UBL-TR remain future work.
6. **Phase 6** (first pass done, then two mapping-engine expansions) — standalone web UI (`apps/web/` + `services/web-api/`): React/Vite frontend (sidebar nav, internal design system), Fastify+Drizzle API backed by Postgres (an existing local Postgres.app instance — see the build note above, not the originally-planned Docker container), giving Tier 2 a visual surface as a second client of the Phase 3/4/5 backend. Shipped: Generate, Inspect & Validate, and an interactive Mapping tab. The mapping tool went through two substantial expansions past its first pass (EDIFACT→UBL only, ~12 fields, positional addressing that didn't survive a different line count):
   - **Pass 2**: source-field addressing moved from raw segment position to tag+occurrence so a saved profile generalizes across documents with different line counts (a profile built from a 2-line sample correctly produces however many output lines a 1-line or 30-line document needs); the mappable field set grew to ~40 (full addresses, tax IDs, payment terms/means, tax totals, line-level tax category, references); target fields can be mapped to a constant value instead of only a source field.
   - **Pass 3 (any-to-any)**: EDIFACT, UBL, and CII/ZUGFeRD can each be the source *or* the target, in any combination (12 meaningful pairs, all verified through the real MCP protocol). Required generalizing the addressing scheme itself — `xmlmap.py` extends the same "tag + occurrence, header-scope vs. line-group-template" model from EDIFACT segments to XML elements (addressed by parent+own tag, since a leaf name like "ID" or "Name" repeats under many different XML parents) — plus a target builder per format (`edifact.build_edifact_invoic`, `zugferd.canonical_to_cii_data_dict` + the existing `ubl.build_invoice_xml`), each reporting which canonical fields it has no representation for rather than silently dropping them.
   - **Pass 4 (unified IR)**: the parallel EDIFACT-addressing and XML-addressing implementations from Pass 3 got collapsed into one shared engine (`ir.py`) — a single tree-node type with generic scope/flatten/extract functions, fed by a small per-format adapter (`edifact.to_ir`, `xmlmap.to_ir`) that converts each source format into that same tree shape. Every source field is now addressed identically (`{parent_tag, tag, occurrence}`) regardless of format, which also simplified the DB/API/frontend types (one ref shape instead of a union). Re-verified against the same 12-combination test suite with identical results before and after.
   - **Pass 5 (create without a source document)**: added a `build_document` MCP tool + `/api/documents` route + Create tab, for building a document directly from typed-in field values rather than mapping one from an existing document. Reuses the same canonical header/line field catalog as the Mapping tab and the same `mapping.py` target-construction step (`build_target`, made public and shared between `run_mapping` and `build_document`) — so required-field checks, per-target-format field support, and dropped-field reporting are identical whether the values came from a mapped source document or were entered by hand. Verified for all four target formats through both the direct MCP protocol and the HTTP API.

   X12 and UBL-TR remain out of scope for mapping (as for everything else in this service) — no parser exists for either format. Deferred to a follow-up pass: audit/history dashboard.
