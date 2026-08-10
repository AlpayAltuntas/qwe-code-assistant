"""EDI/e-invoicing MCP server: six typed, allowlisted tools.

No generic shell/code-execution tool exists here at all, per
docs/threat-model.md E1. Every tool is a fixed Python function with a
typed signature — the model can request one of exactly these
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
from mcp_server.mapping import build_target, describe_source_fields, map_edifact_invoic_to_ubl, run_mapping
from mcp_server.synth import (
    generate_synthetic_edifact_invoic,
    generate_synthetic_ubl_invoice,
    generate_synthetic_zugferd_invoice,
)
from mcp_server.ubl import build_invoice_xml
from mcp_server.ubl import validate as ubl_validate
from mcp_server.zugferd import assemble_pdf, extract_cii_from_pdf
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


def _finalize_target_output(output: str, notes: list[str], to_format: "MappingTargetFormat") -> dict:
    """Shared by apply_mapping_profile and build_document: validates the
    built target document and shapes the response (including the
    zugferd PDF-assembly step), so both entry points return the exact
    same {format, notes, validation, content, ...} shape."""
    if to_format == "edifact":
        parsed = edifact_tokenize(output)
        validation = edifact_validate_structure(parsed)
    elif to_format == "ubl":
        validation = ubl_validate(output)
    else:  # cii or zugferd — both produce CII XML first
        validation = zugferd_validate_cii(output)

    response = {
        "format": to_format,
        "notes": notes,
        "validation": [{"level": f.level, "code": f.code, "message": f.message} for f in validation],
    }
    if to_format == "zugferd":
        pdf_bytes = assemble_pdf(output)
        response["content"] = base64.b64encode(pdf_bytes).decode("ascii")
        response["encoding"] = "base64"
        response["cii_xml"] = output
    else:
        response["content"] = output
    return response

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


MappingSourceFormat = Literal["edifact", "ubl", "cii", "zugferd"]
MappingTargetFormat = Literal["edifact", "ubl", "cii", "zugferd"]


@server.tool()
def describe_mapping_source_fields(content: str, format: MappingSourceFormat) -> dict:
    """Analyzes a sample document (EDIFACT INVOIC, UBL Invoice, CII, or a
    ZUGFeRD/Factur-X PDF) and returns the addressable source fields for
    building a mapping profile in the web UI's Mapping tab: header-scope
    fields (everything outside line-item groups) and a line-item
    *template* (fields from the first detected line-item group only,
    since a profile maps every line group the same relative way). Every
    field, regardless of source format, is addressed the same way —
    {parent_tag, tag, occurrence} — not raw document position, so
    mappings built from these addresses generalize across documents
    where line counts (or other counts) differ; see ir.py for how
    EDIFACT's segment/element/component shape and XML's real nesting
    both convert into one addressable tree. For format='zugferd',
    `content` must be a base64-encoded PDF."""
    check_size(content)

    def _describe() -> dict:
        if format == "zugferd":
            xml_text = _cii_xml_from_content(content, format)
            return describe_source_fields(xml_text, "cii")
        return describe_source_fields(content, format)

    try:
        return run_with_timeout(_describe)
    except ParseTimeout as exc:
        return {"error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"could not parse content: {exc}"}


@server.tool()
def apply_mapping_profile(
    content: str,
    field_mappings: list[dict],
    from_format: MappingSourceFormat = "edifact",
    to_format: MappingTargetFormat = "ubl",
) -> dict:
    """Apply a user-specified field mapping (built via describe_mapping_
    source_fields + the web UI's Mapping tab, not the automatic map_format
    correspondence table) to a document in any of EDIFACT/UBL/CII/ZUGFeRD,
    producing output in any of those formats. Each entry in field_mappings
    is {"target_field": str, "source": {...}}. `source` is either
    {"kind": "field", "ref": {"parent_tag": str, "tag": str, "occurrence":
    int}} — the same address shape regardless of source format: for
    EDIFACT, parent_tag is the segment tag and tag is a synthesized
    "e<element_index>.c<component_index>" position label; for UBL/CII,
    parent_tag/tag are the containing/leaf XML element names (see ir.py) —
    or {"kind": "constant", "value": str} (a fixed value, e.g. for a
    field the source format doesn't carry). target_field is either a header field name
    (invoice_id, issue_date, due_date, invoice_type_code, currency,
    buyer_reference, order_reference, contract_reference,
    payment_means_code, payment_id, payment_terms_note,
    supplier_*/customer_* name+address+tax_id+email, tax_exclusive_amount,
    tax_inclusive_amount, tax_total_amount, tax_category_id, tax_percent,
    payable_amount) or a line field of the form "line.<subfield>"
    (item_name, item_description, buyers_item_id, sellers_item_id,
    quantity, unit_code, line_extension_amount, price_amount,
    tax_category_id, tax_percent) — applied once per detected line-item
    group in the actual input, so one definition produces however many
    output lines the document actually has. Not every field has a home in
    every target format (e.g. this EDIFACT builder has no address
    fields) — fields dropped for that reason are reported in `notes`, not
    silently discarded. For from_format='zugferd', `content` must be a
    base64-encoded PDF; for to_format='zugferd', the response's `content`
    is a base64-encoded PDF (with `cii_xml` also included, same
    convention as generate_synthetic_invoice)."""
    check_size(content)

    def _apply():
        if from_format == "zugferd":
            resolved_content = _cii_xml_from_content(content, from_format)
            resolved_source_format = "cii"
        else:
            resolved_content = content
            resolved_source_format = from_format

        build_target_format = "cii" if to_format == "zugferd" else to_format
        return run_mapping(resolved_content, resolved_source_format, field_mappings, build_target_format)

    try:
        result = run_with_timeout(_apply)
    except ParseTimeout as exc:
        return {"error": str(exc)}

    if result.output is None:
        return {"error": "mapping incomplete", "notes": result.notes}

    return _finalize_target_output(result.output, result.notes, to_format)


@server.tool()
def build_document(
    header: dict,
    lines: list[dict],
    to_format: MappingTargetFormat,
) -> dict:
    """Build a document directly from field values — no source document
    or field mapping required. Use this when the user wants to create an
    EDIFACT/UBL/CII/ZUGFeRD document by entering the data themselves
    rather than mapping it from an existing document (that's
    apply_mapping_profile's job). `header` is a dict of header field
    values keyed by the same target_field names apply_mapping_profile
    documents (invoice_id, issue_date, supplier_name, ...); `lines` is a
    list of dicts, one per line item, each keyed by the line subfield
    names (item_name, quantity, price_amount, ...) without the "line."
    prefix. Not every field has a home in every target format — fields
    with nowhere to go are reported in the response's `notes`, not
    silently dropped. For to_format='zugferd', the response's `content`
    is a base64-encoded PDF (with `cii_xml` also included, same
    convention as generate_synthetic_invoice)."""

    def _build():
        build_to_format = "cii" if to_format == "zugferd" else to_format
        return build_target(header, lines, build_to_format)

    try:
        output, notes = run_with_timeout(_build)
    except ParseTimeout as exc:
        return {"error": str(exc)}

    if output is None:
        return {"error": "could not build document", "notes": notes}

    return _finalize_target_output(output, notes, to_format)


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
