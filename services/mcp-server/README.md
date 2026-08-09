# MCP server (Phases 4-5)

Exposes the EDI/e-invoicing toolset as four typed, allowlisted MCP tools over
stdio, launched by Continue via the `mcpServers:` entry in
`apps/vscode-config/config.yaml`. No generic shell/code-execution tool
exists — see `docs/threat-model.md` E1.

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
