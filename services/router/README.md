# Router service (Phase 3)

Hybrid-cascade domain router + cited RAG retrieval over the EDI/e-invoicing
spec corpus, described in `docs/architecture.md`. Loopback-only, token-authed
FastAPI service; see `docs/threat-model.md` (S1/S2/T1/R1/R2/I1-I3) for the
security rationale behind the design choices below.

## Setup

```sh
uv sync
uv run router-ingest fetch          # download public EDIFACT/UBL spec sources into staging/
uv run router-ingest promote --all  # explicit trusted-corpus promotion (checksums + logs each doc)
uv run router-ingest index          # chunk, embed (via Ollama), and upsert into the local Chroma store
uv run router-serve                 # starts the API on 127.0.0.1:8787
```

`router-serve` writes a per-machine auth token to `.router-token` (0600
permissions) on first run. Every request to `/route` and `/retrieve` must
carry `Authorization: Bearer <token>` — see threat-model.md S2.

## Corpus (Phase 3 scope: EDIFACT INVOIC + UBL Invoice)

- `edifact_d01b_invoic.html` — UN/EDIFACT D01B INVOIC segment clarifications
- `ubl_2.1_invoice.xsd` + the UBL 2.1 CommonAggregateComponents/CommonBasicComponents
  schemas — OASIS UBL 2.1 Invoice document type and its component library

Adding a new spec format means: add a `(filename, url)` entry to `SOURCES` in
`ingest.py`, add a `parse_*` function in `parsing.py`, and register a new
`DomainConfig` in `domains.py` if it's a new domain rather than more EDI
coverage.

## Router cascade

Stage 0 (regex/keyword, word-boundary matched — not substring, to avoid
false hits like "edi" inside "edit"), Stage 1 (embedding similarity against
the domain's Chroma collection), Stage 2 (rare schema-constrained LLM
fallback, enum-only output). See `cascade.py` and `docs/architecture.md`.

## Endpoints

- `GET /health`
- `POST /route {message, override?}` → activation decision + why (stage,
  confidence, matched signals)
- `POST /retrieve {message, domain, k}` → cited chunks, each wrapped in an
  `<<UNTRUSTED_SPEC_REFERENCE>>` delimiter for downstream prompt assembly
- `POST /context {fullInput, query, options, workspacePath?}` → the single
  endpoint Continue's built-in `http` context provider actually calls (see
  `apps/vscode-config/config.yaml`'s `context:` list, entry named
  "EDI Router"). Combines `/route` + `/retrieve` into one call, returning
  `[]` when the router doesn't activate.

Decisions and retrievals are logged to `data/logs/*.jsonl` (append-only,
message content hashed/truncated/redacted — see threat-model.md I3/R1/R2).

## Continue integration: invoke with `@EDI Router`

A `config.ts`-based `CustomContextProvider` (auto-injected on every message
via `experimental.defaultContext`) was tried first, per Continue's own type
definitions. It never fired — Continue's current YAML "Hub" config
resolution doesn't appear to consult `config.ts`. The `http` context
provider declared in `config.yaml` is the integration that actually works,
but providers listed under `context:` are only available for manual
`@`-invocation in this Continue version, not auto-attached to every
message. So: type `@EDI Router <your message>` in Continue chat. Everything
downstream of that keystroke (classification, retrieval, citations,
override) works exactly as designed. See `docs/architecture.md`'s
"Invocation note" for the full story.

## Not yet wired up

The EDI *tool* calls the specialist layer will eventually request
(`parse_edi`, `validate_with_citation`, `map_format`,
`generate_synthetic_invoice`) don't exist yet — that's `services/mcp-server`,
Phase 4.
