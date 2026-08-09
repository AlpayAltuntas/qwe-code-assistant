# MCP server (Phase 4 placeholder)

Will expose the EDI/e-invoicing toolset (`parse_edi`, `validate_with_citation`, `map_format`, `generate_synthetic_invoice`) as typed, allowlisted MCP tools, backed by format modules (EDIFACT, X12, UBL/CII/PEPPOL/UBL-TR, ZUGFeRD/Factur-X) and a Docker sandbox for any untrusted parsing or generated-code execution.

Not implemented yet — Tier 1 (the generalist) does not depend on this service.
