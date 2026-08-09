# MCP server (Phase 4)

Exposes the EDI/e-invoicing toolset as four typed, allowlisted MCP tools over
stdio, launched by Continue via the `mcpServers:` entry in
`apps/vscode-config/config.yaml`. No generic shell/code-execution tool
exists — see `docs/threat-model.md` E1.

## Setup

```sh
uv sync
uv run mcp-fetch-schemas   # downloads the OASIS UBL 2.1 XSD chain into schemas/
```

Continue starts the server itself (`uv run --directory <path> edi-mcp-server`)
— there's no separate process to launch by hand. To run/test it standalone:

```sh
uv run edi-mcp-server
```

## Tools

- **`parse_edi(content, format)`** — segment-by-segment (EDIFACT) or
  element-by-element (UBL) breakdown, with curated human-readable segment
  descriptions for EDIFACT.
- **`validate_with_citation(content, format)`** — deterministic verdict
  only: EDIFACT gets structural checks (envelope presence, UNH/UNT control
  counts, known segment tags), UBL gets real XSD schema validation against
  the OASIS UBL 2.1 Invoice schema chain. The verdict never comes from the
  model (docs/threat-model.md T2). Findings are enriched with cited spec
  chunks from the Phase 3 router when it's running — omitted, not
  fabricated, if it isn't.
- **`map_format(content, from_format, to_format)`** — EDIFACT INVOIC → UBL
  Invoice only for now. Covers the common field correspondences (BGM, DTM
  issue date, NAD buyer/seller, MOA totals/line amounts, LIN/IMD/QTY/PRI
  line items) — not the full spec; unmapped segments and mapping notes are
  returned alongside the draft so nothing is silently dropped. Returns
  text only — never writes to the user's files (docs/threat-model.md T3).
- **`generate_synthetic_invoice(format, num_lines, seed)`** — Faker-sourced
  fictional EDIFACT INVOIC or UBL Invoice, never derived from real data.

## Scope and known limitations

- **Formats**: EDIFACT INVOIC ↔ UBL Invoice only, matching the Phase 3
  corpus. X12/UBL-TR/CII/ZUGFeRD are Phase 5.
- **No Docker sandbox yet**: mitigated in-process instead — hard input-size
  caps and wall-clock parse timeouts (`limits.py`), and `defusedxml` used
  for the XML tree that's actually validated, not just a well-formedness
  pre-check (see the fix noted in `ubl.py` — passing the safely-parsed
  element into `xmlschema.iter_errors()` rather than re-parsing raw text).
- **Ollama tool-calling reliability**: all four tools are verified correct
  via direct MCP protocol calls (`list_tools` + `call_tool`). Invoking them
  through Continue's Agent mode with `qwen3-coder:30b` via Ollama is
  currently unreliable — the model sometimes emits malformed tool-call
  syntax or answers directly instead of calling the tool. This matches
  publicly-documented Ollama/Qwen3-coder tool-calling bugs (as of mid-2026,
  Ollama 0.32.6) and isn't something to fix in this codebase — revisit when
  Ollama ships a fix.
