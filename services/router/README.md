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

## Corpus (EDIFACT INVOIC + UBL Invoice + CII/ZUGFeRD, 5,011 chunks)

- `edifact_d01b_invoic.html` — UN/EDIFACT D01B INVOIC segment clarifications
- `ubl_2.1_invoice.xsd` + the UBL 2.1 CommonAggregateComponents/CommonBasicComponents
  schemas — OASIS UBL 2.1 Invoice document type and its component library
- `cii_100pd22b_reusable_aggregate_business_information_entity.xsd` (Phase 5)
  — the CII (Cross Industry Invoice) schema used by ZUGFeRD/Factur-X, with
  real per-element documentation. Only available inside the `factur-x`
  PyPI package's sdist (no stable public URL for the annotated version —
  `cmd_fetch` downloads the sdist tarball and extracts just this one file;
  see `_fetch_cii_schema` in `ingest.py`).

Adding a new spec format means: add a `(filename, url)` entry to `SOURCES`
in `ingest.py` (or a special-cased fetch step, if it's not a plain direct
URL — see `_fetch_cii_schema`), add a `parse_*` function in `parsing.py` if
the document shape is genuinely new (`parse_xsd_documentation` already
covers any XSD with per-element `xsd:documentation`, CCTS-structured or
plain — that's how the CII schema needed zero new parsing code), and
register a new `DomainConfig` in `domains.py` if it's a new domain rather
than more EDI coverage.

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

## Related: EDI tool functions

The EDI *tool* calls (`parse_edi`, `validate_with_citation`, `map_format`,
`generate_synthetic_invoice`) live in `services/mcp-server` (Phases 4-5) and
call this service's `/retrieve` endpoint internally for citations — see
that service's README.
