"""EDI/e-invoicing MCP server: four typed, allowlisted tools.

No generic shell/code-execution tool exists here at all, per
docs/threat-model.md E1. Every tool is a fixed Python function with a
typed signature — the model can request one of exactly these four
operations, nothing else.
"""

from typing import Literal

import defusedxml.ElementTree as safe_ET
from mcp.server.mcpserver import MCPServer

from mcp_server.citations import fetch_citations
from mcp_server.edifact import tokenize as edifact_tokenize
from mcp_server.edifact import validate_structure as edifact_validate_structure
from mcp_server.limits import ParseTimeout, check_size, parse_timeout
from mcp_server.mapping import map_edifact_invoic_to_ubl
from mcp_server.synth import generate_synthetic_edifact_invoic, generate_synthetic_ubl_invoice
from mcp_server.ubl import build_invoice_xml
from mcp_server.ubl import validate as ubl_validate

server = MCPServer(
    name="edi-invoicing",
    instructions=(
        "Tools for EDI/e-invoicing work: parsing, spec-cited validation, "
        "EDIFACT INVOIC -> UBL Invoice mapping, and synthetic test-invoice "
        "generation. Validation verdicts are deterministic (schema/structural "
        "checks), never inferred — use validate_with_citation rather than "
        "eyeballing a message when the user asks if something is valid."
    ),
)


def _guarded(content: str):
    check_size(content)
    return parse_timeout()


@server.tool()
def parse_edi(content: str, format: Literal["edifact", "ubl"]) -> dict:
    """Parse an EDIFACT INVOIC or UBL Invoice message and explain it
    segment-by-segment (EDIFACT) or element-by-element (UBL)."""
    check_size(content)
    try:
        with parse_timeout():
            if format == "edifact":
                result = edifact_tokenize(content)
                from mcp_server.edifact import SEGMENT_DESCRIPTIONS

                return {
                    "format": "edifact",
                    "segments": [
                        {
                            "tag": s.tag,
                            "description": SEGMENT_DESCRIPTIONS.get(s.tag, "(not in curated set)"),
                            "elements": s.elements,
                        }
                        for s in result.segments
                    ],
                }
            else:
                root = safe_ET.fromstring(content)

                def walk(el, path=""):
                    tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
                    current = f"{path}/{tag}"
                    items = []
                    text = (el.text or "").strip()
                    if text:
                        items.append({"path": current, "text": text})
                    for child in el:
                        items.extend(walk(child, current))
                    return items

                return {"format": "ubl", "elements": walk(root)}
    except ParseTimeout as exc:
        return {"error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - reported, not raised, to the model
        return {"error": f"could not parse as {format}: {exc}"}


@server.tool()
def validate_with_citation(content: str, format: Literal["edifact", "ubl"]) -> dict:
    """Validate an EDIFACT INVOIC or UBL Invoice message. The verdict is
    always deterministic (structural rules for EDIFACT, real XSD schema
    validation for UBL) — never inferred by the model. Findings are
    enriched with cited spec references from the Phase 3 RAG corpus when
    the router service is available."""
    check_size(content)
    try:
        with parse_timeout():
            if format == "edifact":
                result = edifact_tokenize(content)
                findings = edifact_validate_structure(result)
            else:
                findings = ubl_validate(content)
    except ParseTimeout as exc:
        return {"error": str(exc)}

    verdict = "valid" if all(f.level != "error" for f in findings) else "invalid"
    citations = fetch_citations(content, domain="edi", k=3)

    return {
        "format": format,
        "verdict": verdict,
        "findings": [{"level": f.level, "code": f.code, "message": f.message} for f in findings],
        "citations": [
            {"doc_id": c["doc_id"], "section": c["section"], "sha256": c["sha256"], "score": c["score"]}
            for c in citations
        ],
    }


@server.tool()
def map_format(
    content: str,
    from_format: Literal["edifact"] = "edifact",
    to_format: Literal["ubl"] = "ubl",
) -> dict:
    """Draft a mapping of an EDIFACT INVOIC message to a UBL Invoice
    document. Covers the common field correspondences (BGM, DTM issue
    date, NAD buyer/seller, MOA totals and line amounts, LIN/IMD/QTY/PRI
    line items) — not the full spec. Returns text only; never writes to
    the user's files (apply it yourself via a normal diff/edit)."""
    check_size(content)
    if from_format != "edifact" or to_format != "ubl":
        return {"error": "only edifact -> ubl is supported in this pass"}

    try:
        with parse_timeout():
            result = edifact_tokenize(content)
            mapping = map_edifact_invoic_to_ubl(result)
    except ParseTimeout as exc:
        return {"error": str(exc)}

    if mapping.fields is None:
        return {"error": "mapping incomplete", "notes": mapping.notes, "unmapped_segments": mapping.unmapped_segments}

    ubl_xml = build_invoice_xml(mapping.fields)
    validation = ubl_validate(ubl_xml)

    return {
        "ubl_xml": ubl_xml,
        "notes": mapping.notes,
        "unmapped_segments": mapping.unmapped_segments,
        "validation": [{"level": f.level, "code": f.code, "message": f.message} for f in validation],
    }


@server.tool()
def generate_synthetic_invoice(
    format: Literal["edifact", "ubl"],
    num_lines: int = 2,
    seed: int | None = None,
) -> dict:
    """Generate a synthetic (Faker-sourced, entirely fictional) test
    invoice in EDIFACT INVOIC or UBL Invoice format, for use in a test
    suite. Never derived from real customer data. Pass `seed` for a
    reproducible fixture."""
    num_lines = max(1, min(num_lines, 20))
    if format == "edifact":
        content = generate_synthetic_edifact_invoic(seed=seed, num_lines=num_lines)
    else:
        content = generate_synthetic_ubl_invoice(seed=seed, num_lines=num_lines)
    return {"format": format, "content": content}
