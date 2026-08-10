# MCP server (Phases 4-6)

Exposes the EDI/e-invoicing toolset as seven typed, allowlisted MCP tools over
stdio. Two clients launch it: Continue, via the `mcpServers:` entry in
`apps/vscode-config/config.yaml`, and the Phase 6 web UI's Fastify API
(`services/web-api`), which spawns it per call the same way. No generic
shell/code-execution tool exists — see `docs/threat-model.md` E1.

## Setup

```sh
uv sync
uv run mcp-fetch-schemas   # downloads the OASIS UBL 2.1 XSD chain into schemas/
```

CII/ZUGFeRD validation schemas are bundled inside the `factur-x` dependency —
nothing extra to fetch for those.

Continue starts the server itself (`uv run --directory <path> edi-mcp-server`)
— there's no separate process to launch by hand. To run/test it standalone:

```sh
uv run edi-mcp-server
```

## Tools

- **`parse_edi(content, format)`** — segment-by-segment (EDIFACT) or
  element-by-element (UBL/CII) breakdown, with curated human-readable segment
  descriptions for EDIFACT. `format="zugferd"` expects `content` as a
  base64-encoded PDF (the embedded CII XML is extracted automatically);
  `format="cii"` expects raw CII XML text.
- **`validate_with_citation(content, format)`** — deterministic verdict
  only: EDIFACT gets structural checks (envelope presence, UNH/UNT control
  counts, known segment tags), UBL/CII get real XSD schema validation
  (OASIS UBL 2.1 Invoice chain / EN16931 CII, via `factur-x`). The verdict
  never comes from the model (docs/threat-model.md T2). Findings are
  enriched with cited spec chunks from the Phase 3 router when it's
  running — omitted, not fabricated, if it isn't.
- **`map_format(content, from_format, to_format)`** — EDIFACT INVOIC → UBL
  Invoice only (CII isn't a mapping target in this pass). Covers the common
  field correspondences (BGM, DTM issue date, NAD buyer/seller, MOA
  totals/line amounts, LIN/IMD/QTY/PRI line items) — not the full spec;
  unmapped segments and mapping notes are returned alongside the draft so
  nothing is silently dropped. Returns text only — never writes to the
  user's files (docs/threat-model.md T3).
- **`generate_synthetic_invoice(format, num_lines, seed)`** — Faker-sourced
  fictional invoice, never derived from real data. `format="zugferd"`
  returns a base64-encoded PDF/A-3 with a schema-valid CII XML embedded
  (plus the raw `cii_xml` for convenience — the PDF's visual layer is a
  blank placeholder, not a rendered invoice); `format="cii"` returns just
  the XML.
- **`describe_mapping_source_fields(content, format)`** (Phase 6) — analyzes
  a sample (EDIFACT, UBL, CII, or a ZUGFeRD PDF) and returns addressable
  source fields for the Mapping tab's field pickers: header-scope fields
  (everything outside line-item groups) and a line-item *template* (fields
  from the first detected line-item group only — a mapping applies the
  same relative address to every line group a document actually has).
  Every field, regardless of source format, is addressed the same way:
  `{parent_tag, tag, occurrence}` — see `ir.py` for how EDIFACT's
  segment/element/component shape and XML's real nesting both convert into
  one shared tree before anything gets addressed.
- **`apply_mapping_profile(content, field_mappings, from_format, to_format)`**
  (Phase 6, any-to-any since Pass 3) — `map_format`'s user-driven sibling:
  instead of one hardcoded correspondence table, applies field mappings a
  user built themselves (the web UI's Mapping tab, via
  `describe_mapping_source_fields`). `from_format`/`to_format` can each be
  any of `edifact`/`ubl`/`cii`/`zugferd`, independently. Each field_mappings
  entry is `{target_field, source}`, where `source` is either `{kind:
  "field", ref: {parent_tag, tag, occurrence}}` (resolved from the input
  document's own tree) or `{kind: "constant", value}` (a fixed value, for
  data the source format doesn't carry). `target_field` covers ~30 header
  fields (dates, references, payment terms/means, full addresses, tax IDs,
  tax totals) and ~10 line fields (`line.<subfield>`, e.g. `line.item_name`)
  — see `mapping.py`'s `HEADER_TARGET_FIELDS` / `LINE_SUBFIELDS` for the
  full list; not every field has a home in every target format (this
  EDIFACT builder has no address fields, for instance) — what got dropped
  is reported in the response's `notes`, never silently discarded. Line
  targets are applied once per detected line-item group in the *actual*
  input document, so one mapping definition produces however many output
  lines that document actually has — a mapping built from a 2-line sample
  works unchanged on a 1-line or 30-line document, verified for all 12
  meaningful format pairs.
- **`build_document(header, lines, to_format)`** (Phase 6) —
  `apply_mapping_profile`'s sibling for when there's no source document to
  map from at all: builds a target document directly from field values the
  caller supplies. `header` is `{target_field: value}` and `lines` is a list
  of `{subfield: value}` dicts — the same canonical field vocabulary as
  `apply_mapping_profile`'s `target_field`, just supplied directly instead
  of resolved from a source tree. Shares `mapping.py`'s `build_target` (the
  format-agnostic target-construction step) with `apply_mapping_profile`,
  so required-field checks, per-target-format field support, and line
  defaulting behave identically between "map from a document" and "type it
  in by hand". Same response shape as `apply_mapping_profile` (`format`,
  `notes`, `validation`, `content`, plus `encoding`/`cii_xml` for
  `to_format="zugferd"`).

## Scope and known limitations

- **Formats**: EDIFACT INVOIC ↔ UBL Invoice (Phase 4), CII/ZUGFeRD-Factur-X
  added in Phase 5 for parse/validate/generate (not map_format). X12 and
  UBL-TR remain future work.
- **ZUGFeRD/Factur-X is built on the `factur-x` library** (BSD-licensed),
  not a hand-rolled CII schema resolver — UN/CEFACT's full codelist schema
  tree is dozens of files deep (currency codes, country codes, transport
  codes, ...); `factur-x` already bundles a working, tested schema set and
  handles PDF/A-3 + XMP metadata assembly correctly. The Phase 3 router
  corpus's CII documentation source is only available inside that package's
  PyPI sdist (no stable public URL for the annotated schema) —
  `router-ingest fetch` downloads the sdist and extracts just that file;
  see `services/router/src/router/ingest.py`.
- **No Docker sandbox yet**: mitigated in-process instead — hard input-size
  caps and wall-clock parse timeouts (`limits.py`), and `defusedxml`/a
  hardened `lxml.etree.XMLParser` used for the XML tree that's actually
  validated in both `ubl.py` and `zugferd.py`, not just a well-formedness
  pre-check on a separate parse.
- **Parse timeouts use a `ThreadPoolExecutor`, not `signal.alarm`** — the
  original Phase 4 implementation used `signal.alarm`, which only works on
  a process's main thread. It crashed the first time a real MCP tool call
  exercised it, since MCP dispatches tool calls on a worker thread — caught
  during Phase 5 testing, not before. `run_with_timeout()` in `limits.py`
  runs the guarded call in its own thread and bounds `.result()`, which
  works from any calling thread (though it can't forcibly kill a truly
  runaway worker — real enforcement is what the deferred Docker sandbox is
  for).
- **Ollama tool-calling reliability**: all tools are verified correct via
  direct MCP protocol calls (`list_tools` + `call_tool`). Invoking them
  through Continue's Agent mode with `qwen3-coder:30b` via Ollama is
  currently unreliable — the model sometimes emits malformed tool-call
  syntax or answers directly instead of calling the tool. This matches
  publicly-documented Ollama/Qwen3-coder tool-calling bugs (as of mid-2026,
  Ollama 0.32.6) and isn't something to fix in this codebase — revisit when
  Ollama ships a fix.
