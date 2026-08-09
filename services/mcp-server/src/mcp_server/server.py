"""EDI/e-invoicing MCP server: five typed, allowlisted tools.

No generic shell/code-execution tool exists here at all, per
docs/threat-model.md E1. Every tool is a fixed Python function with a
typed signature — the model can request one of exactly these four
operations, nothing else.
"""

import base64
from typing import Literal

import defusedxml.ElementTree as safe_ET
from mcp.server.mcpserver import MCPServer

from mcp_server.citations import fetch_citations
from mcp_server.edifact import tokenize as edifact_tokenize
from mcp_server.edifact import validate_structure as edifact_validate_structure
from mcp_server.limits import ParseTimeout, check_size, run_with_timeout
from mcp_server.mapping import apply_field_mapping, map_edifact_invoic_to_ubl
from mcp_server.synth import (
    generate_synthetic_edifact_invoic,
    generate_synthetic_ubl_invoice,
    generate_synthetic_zugferd_invoice,
)
from mcp_server.ubl import build_invoice_xml
from mcp_server.ubl import validate as ubl_validate
from mcp_server.zugferd import extract_cii_from_pdf
from mcp_server.zugferd import validate_cii as zugferd_validate_cii

EdiFormat = Literal["edifact", "ubl", "cii", "zugferd"]


def _walk_xml_tree(el, path: str = "") -> list[dict]:
    tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
    current = f"{path}/{tag}"
    items = []
    text = (el.text or "").strip()
    if text:
        items.append({"path": current, "text": text})
    for child in el:
        items.extend(_walk_xml_tree(child, current))
    return items


def _cii_xml_from_content(content: str, format: EdiFormat) -> str:
    """format='cii' -> content is raw XML text. format='zugferd' ->
    content is a base64-encoded PDF; extract the embedded CII XML."""
    if format == "cii":
        return content
    pdf_bytes = base64.b64decode(content)
    _filename, xml_text = extract_cii_from_pdf(pdf_bytes)
    return xml_text

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


@server.tool()
def parse_edi(content: str, format: EdiFormat) -> dict:
    """Parse an EDIFACT INVOIC, UBL Invoice, or Factur-X/ZUGFeRD (CII)
    message and explain it segment-by-segment (EDIFACT) or
    element-by-element (UBL/CII). For format='zugferd', `content` must be
    a base64-encoded PDF (the embedded CII XML is extracted automatically);
    for format='cii', `content` is the raw CII XML text directly."""
    check_size(content)

    def _parse() -> dict:
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
        elif format == "ubl":
            root = safe_ET.fromstring(content)
            return {"format": "ubl", "elements": _walk_xml_tree(root)}
        else:
            xml_text = _cii_xml_from_content(content, format)
            root = safe_ET.fromstring(xml_text)
            return {"format": format, "elements": _walk_xml_tree(root)}

    try:
        return run_with_timeout(_parse)
    except ParseTimeout as exc:
        return {"error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - reported, not raised, to the model
        return {"error": f"could not parse as {format}: {exc}"}


@server.tool()
def validate_with_citation(content: str, format: EdiFormat) -> dict:
    """Validate an EDIFACT INVOIC, UBL Invoice, or Factur-X/ZUGFeRD (CII)
    message. The verdict is always deterministic (structural rules for
    EDIFACT, real XSD schema validation for UBL/CII) — never inferred by
    the model. Findings are enriched with cited spec references from the
    Phase 3 RAG corpus when the router service is available. For
    format='zugferd', `content` must be a base64-encoded PDF; for
    format='cii', `content` is the raw CII XML text."""
    check_size(content)

    def _validate():
        if format == "edifact":
            result = edifact_tokenize(content)
            return edifact_validate_structure(result)
        elif format == "ubl":
            return ubl_validate(content)
        else:
            xml_text = _cii_xml_from_content(content, format)
            return zugferd_validate_cii(xml_text)

    try:
        findings = run_with_timeout(_validate)
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

    def _map():
        result = edifact_tokenize(content)
        return map_edifact_invoic_to_ubl(result)

    try:
        mapping = run_with_timeout(_map)
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
def apply_mapping_profile(
    content: str,
    field_mappings: list[dict],
    from_format: Literal["edifact"] = "edifact",
    to_format: Literal["ubl"] = "ubl",
) -> dict:
    """Apply a user-specified field mapping (built via the web UI's
    Mapping tab, not the automatic map_format correspondence table) to an
    EDIFACT INVOIC message, producing UBL Invoice XML. Each entry in
    field_mappings is {"target_field": str, "source": {"segment_index":
    int, "element_index": int, "component_index": int}}; target_field is
    either a header field name (invoice_id, issue_date, invoice_type_code,
    currency, supplier_name, customer_name, payable_amount) or a line
    field of the form "line_<N>.<subfield>" where subfield is one of
    item_name/quantity/unit_code/line_extension_amount/price_amount. The
    source indices are positional into this exact message's parsed
    segments — a mapping profile is tied to documents with the same
    segment shape as the sample it was built from."""
    check_size(content)
    if from_format != "edifact" or to_format != "ubl":
        return {"error": "only edifact -> ubl is supported in this pass"}

    def _apply():
        result = edifact_tokenize(content)
        return apply_field_mapping(result, field_mappings)

    try:
        mapping = run_with_timeout(_apply)
    except ParseTimeout as exc:
        return {"error": str(exc)}

    if mapping.fields is None:
        return {"error": "mapping incomplete", "notes": mapping.notes}

    ubl_xml = build_invoice_xml(mapping.fields)
    validation = ubl_validate(ubl_xml)

    return {
        "ubl_xml": ubl_xml,
        "notes": mapping.notes,
        "validation": [{"level": f.level, "code": f.code, "message": f.message} for f in validation],
    }


@server.tool()
def generate_synthetic_invoice(
    format: EdiFormat,
    num_lines: int = 2,
    seed: int | None = None,
) -> dict:
    """Generate a synthetic (Faker-sourced, entirely fictional) test
    invoice in EDIFACT INVOIC, UBL Invoice, CII (raw XML), or ZUGFeRD/
    Factur-X (PDF/A-3 with the CII XML embedded) format, for use in a
    test suite. Never derived from real customer data. Pass `seed` for a
    reproducible fixture. For format='zugferd' the response's `content`
    is a base64-encoded PDF (encoding='base64'); a `cii_xml` field is
    also included for convenience since the PDF's visual layer is a
    blank placeholder — the XML is the authoritative content."""
    num_lines = max(1, min(num_lines, 20))
    if format == "edifact":
        return {"format": format, "content": generate_synthetic_edifact_invoic(seed=seed, num_lines=num_lines)}
    if format == "ubl":
        return {"format": format, "content": generate_synthetic_ubl_invoice(seed=seed, num_lines=num_lines)}

    xml_text, pdf_bytes = generate_synthetic_zugferd_invoice(seed=seed, num_lines=num_lines)
    if format == "cii":
        return {"format": format, "content": xml_text}
    return {
        "format": format,
        "content": base64.b64encode(pdf_bytes).decode("ascii"),
        "encoding": "base64",
        "cii_xml": xml_text,
    }
