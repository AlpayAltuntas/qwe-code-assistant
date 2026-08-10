"""EDIFACT INVOIC (D01B) -> UBL 2.1 Invoice field mapping.

Deliberately partial: covers the segments/qualifiers that carry the core
invoice header and line-item data (BGM, DTM/137, NAD BY|SU, MOA totals
and line amounts, LIN/IMD/QTY/PRI groups). A full implementation-guideline
mapping (PEPPOL BIS, EU CEN) is hundreds of field correspondences — this
is the common subset, not the complete spec. Anything not recognized is
reported back as an "unmapped" note rather than silently dropped.

Never writes to the user's files — returns text for review, per
docs/threat-model.md T3 (all repo writes go through the editor's own
diff/apply UI, not this service).
"""

import re
from dataclasses import dataclass, field

import defusedxml.ElementTree as safe_ET

from mcp_server import ir, xmlmap
from mcp_server.edifact import EDIFACT_SUPPORTED_HEADER_FIELDS, EDIFACT_SUPPORTED_LINE_FIELDS, LINE_GROUP_IR_TAG
from mcp_server.edifact import ParseResult, SEGMENT_DESCRIPTIONS, build_edifact_invoic
from mcp_server.edifact import to_ir as edifact_to_ir
from mcp_server.edifact import tokenize as edifact_tokenize
from mcp_server.ubl import InvoiceFields, build_invoice_xml
from mcp_server.zugferd import CII_SUPPORTED_HEADER_FIELDS, CII_SUPPORTED_LINE_FIELDS
from mcp_server.zugferd import build_cii_xml, canonical_to_cii_data_dict

NAD_QUALIFIER_TO_ROLE = {"SU": "supplier", "BY": "buyer", "SE": "seller"}
MOA_TOTAL_QUALIFIERS = {"77", "128", "9"}  # invoice/payable total (best-effort, see module docstring)
MOA_LINE_QUALIFIER = "203"  # line item amount
DTM_ISSUE_DATE_QUALIFIER = "137"
QTY_INVOICED_QUALIFIER = "47"


@dataclass
class MappingResult:
    fields: InvoiceFields | None
    unmapped_segments: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _dtm_to_iso(value: str, format_code: str) -> str:
    if format_code == "102" and len(value) == 8:  # CCYYMMDD
        return f"{value[0:4]}-{value[4:6]}-{value[6:8]}"
    return value


def map_edifact_invoic_to_ubl(result: ParseResult) -> MappingResult:
    segments = result.segments
    unmapped: list[str] = []
    notes: list[str] = []

    invoice_id = ""
    invoice_type_code = "380"
    issue_date = ""
    currency = "EUR"
    supplier_name = ""
    customer_name = ""
    payable_amount = ""
    lines: list[dict] = []

    current_line: dict | None = None

    def flush_line():
        nonlocal current_line
        if current_line is not None:
            current_line.setdefault("quantity", "0")
            current_line.setdefault("unit_code", "EA")
            current_line.setdefault("line_extension_amount", "0.00")
            current_line.setdefault("item_name", f"Line {current_line['id']}")
            if "price_amount" not in current_line:
                try:
                    qty = float(current_line["quantity"]) or 1.0
                    current_line["price_amount"] = f"{float(current_line['line_extension_amount']) / qty:.2f}"
                    notes.append(f"line {current_line['id']}: price derived from amount/quantity (no PRI segment)")
                except (ValueError, ZeroDivisionError):
                    current_line["price_amount"] = current_line["line_extension_amount"]
            lines.append(current_line)
            current_line = None

    for seg in segments:
        tag, els = seg.tag, seg.elements

        if tag == "BGM":
            if els:
                invoice_type_code = els[0][0] if els[0] else invoice_type_code
            if len(els) > 1:
                invoice_id = els[1][0]

        elif tag == "DTM" and els and els[0]:
            qualifier = els[0][0]
            if qualifier == DTM_ISSUE_DATE_QUALIFIER and len(els[0]) > 1:
                value = els[0][1]
                fmt = els[0][2] if len(els[0]) > 2 else ""
                issue_date = _dtm_to_iso(value, fmt)

        elif tag == "NAD" and els and els[0]:
            qualifier = els[0][0]
            role = NAD_QUALIFIER_TO_ROLE.get(qualifier)
            name = None
            if len(els) > 3 and els[3]:
                name = " ".join(c for c in els[3] if c)
            if not name and len(els) > 1 and els[1]:
                name = f"Party {els[1][0]}"
            if role == "supplier" and name:
                supplier_name = name
            elif role == "buyer" and name:
                customer_name = name
            elif not role:
                unmapped.append(seg.raw)

        elif tag == "MOA" and els and els[0]:
            qualifier = els[0][0]
            amount = els[0][1] if len(els[0]) > 1 else None
            if amount is None:
                unmapped.append(seg.raw)
            elif qualifier in MOA_TOTAL_QUALIFIERS:
                payable_amount = amount
            elif qualifier == MOA_LINE_QUALIFIER and current_line is not None:
                current_line["line_extension_amount"] = amount
            else:
                unmapped.append(seg.raw)

        elif tag == "LIN":
            flush_line()
            line_id = els[0][0] if els and els[0] else str(len(lines) + 1)
            current_line = {"id": line_id}
            if len(els) > 2 and els[2]:
                current_line["item_name"] = els[2][0]

        elif tag == "IMD" and current_line is not None and len(els) > 2 and els[2]:
            text = " ".join(c for c in els[2] if c)
            if text:
                current_line["item_name"] = text

        elif tag == "QTY" and current_line is not None and els and els[0]:
            qualifier = els[0][0]
            if qualifier == QTY_INVOICED_QUALIFIER and len(els[0]) > 1:
                current_line["quantity"] = els[0][1]

        elif tag == "PRI" and current_line is not None and els and els[0] and len(els[0]) > 1:
            current_line["price_amount"] = els[0][1]

        elif tag in ("UNH", "UNT", "UNB", "UNZ", "CUX"):
            if tag == "CUX" and els and els[0] and len(els[0]) > 1:
                currency = els[0][1]
        else:
            unmapped.append(seg.raw)

    flush_line()

    if not invoice_id or not issue_date or not supplier_name or not customer_name or not lines:
        missing = [
            name
            for name, val in [
                ("invoice id (BGM)", invoice_id),
                ("issue date (DTM+137)", issue_date),
                ("supplier name (NAD+SU)", supplier_name),
                ("customer name (NAD+BY)", customer_name),
                ("at least one line (LIN)", lines),
            ]
            if not val
        ]
        notes.append(f"could not build a complete UBL Invoice — missing: {', '.join(missing)}")
        return MappingResult(fields=None, unmapped_segments=unmapped, notes=notes)

    fields = InvoiceFields(
        invoice_id=invoice_id,
        issue_date=issue_date,
        currency=currency,
        invoice_type_code=invoice_type_code,
        supplier_name=supplier_name,
        customer_name=customer_name,
        payable_amount=payable_amount or "0.00",
        lines=lines,
    )
    return MappingResult(fields=fields, unmapped_segments=unmapped, notes=notes)


# --- User-driven field mapping (Phase 6 mapping tool) -----------------------
#
# Unlike map_edifact_invoic_to_ubl above (a fixed, hardcoded correspondence
# table), this lets a user specify their own source->target correspondences
# for ANY of EDIFACT/UBL/CII in either direction, via the web UI, saved as
# a reusable "mapping profile".
#
# Source references are addressed by tag/element-position (EDIFACT — see
# edifact.group_segments) or by parent+tag position (UBL/CII XML — see
# xmlmap.py) — occurrence-of-that-shape, not raw document position. Header
# fields are resolved against the message's header-scope content; line
# fields are resolved against *every* detected line group using the same
# relative address, producing one output line per group. That's what makes
# a saved profile generalize: apply it to an invoice with 3 line items or
# 30, and each gets mapped the same way — a profile isn't tied to the exact
# shape of the sample it was built from, only to the *pattern* (which field
# holds what, and in what position relative to each repeating line unit).
#
# A source can also be a constant (`{"kind": "constant", "value": ...}`)
# instead of a field reference — common in real mapping tools for values
# the source format doesn't carry at all (e.g. always setting a country
# code). Applied to a line target, the same constant is used for every
# generated line.
#
# The canonical field vocabulary below (HEADER_TARGET_FIELDS/LINE_SUBFIELDS)
# is shared across all three target formats — not every field has a home in
# every format (EDIFACT's D01B INVOIC subset here doesn't carry full
# addresses or tax breakdown, for instance); each build_* function reports
# what it had to drop rather than silently discarding it. X12 and UBL-TR
# aren't supported as either source or target — there's no parser for
# either format in this service yet, a separate undertaking from
# generalizing this mapping engine.

HEADER_TARGET_FIELDS = {
    "invoice_id",
    "issue_date",
    "due_date",
    "invoice_type_code",
    "currency",
    "buyer_reference",
    "order_reference",
    "contract_reference",
    "payment_means_code",
    "payment_id",
    "payment_terms_note",
    "supplier_name",
    "supplier_street",
    "supplier_city",
    "supplier_postal_zone",
    "supplier_country_code",
    "supplier_tax_id",
    "supplier_email",
    "customer_name",
    "customer_street",
    "customer_city",
    "customer_postal_zone",
    "customer_country_code",
    "customer_tax_id",
    "customer_email",
    "tax_exclusive_amount",
    "tax_inclusive_amount",
    "tax_total_amount",
    "tax_category_id",
    "tax_percent",
    "payable_amount",
}
DATE_FIELDS = {"issue_date", "due_date"}
LINE_SUBFIELDS = {
    "item_name",
    "item_description",
    "buyers_item_id",
    "sellers_item_id",
    "quantity",
    "unit_code",
    "line_extension_amount",
    "price_amount",
    "tax_category_id",
    "tax_percent",
}
_CCYYMMDD = re.compile(r"^\d{8}$")


SOURCE_FORMATS = ("edifact", "ubl", "cii")
TARGET_FORMATS = ("edifact", "ubl", "cii", "zugferd")

# What each target format's builder actually has a home for — used to warn
# about dropped fields *before* lines get their generic defaults filled in
# (so a field the user never even tried to map doesn't get reported as
# "dropped"). UBL supports the full canonical set; EDIFACT (this simplified
# D01B builder) and CII (via the factur-x library) each support a subset —
# see edifact.EDIFACT_SUPPORTED_*_FIELDS / zugferd.CII_SUPPORTED_*_FIELDS.
TARGET_SUPPORTED_HEADER_FIELDS = {
    "ubl": HEADER_TARGET_FIELDS,
    "edifact": EDIFACT_SUPPORTED_HEADER_FIELDS | {"supplier_name", "customer_name"},
    "cii": CII_SUPPORTED_HEADER_FIELDS,
    "zugferd": CII_SUPPORTED_HEADER_FIELDS,
}
TARGET_SUPPORTED_LINE_FIELDS = {
    "ubl": LINE_SUBFIELDS,
    "edifact": EDIFACT_SUPPORTED_LINE_FIELDS,
    "cii": CII_SUPPORTED_LINE_FIELDS,
    "zugferd": CII_SUPPORTED_LINE_FIELDS,
}


def _build_scope_for_source(content: str, source_format: str) -> ir.Scope:
    """The one place that knows how to turn each source format into the
    unified IR and find its line-item groups within it — everything
    downstream (field listing, value resolution) is truly format-agnostic
    from here on, operating only on ir.Node/ir.Scope."""
    if source_format == "edifact":
        result: ParseResult = edifact_tokenize(content)
        root = edifact_to_ir(result)
        return ir.build_scope(root, LINE_GROUP_IR_TAG)
    elif source_format in ("ubl", "cii"):
        xml_root = safe_ET.fromstring(content)
        root = xmlmap.to_ir(xml_root)
        return ir.build_scope(root, xmlmap.LINE_CONTAINER_LOCAL_TAG[source_format])
    else:
        raise ValueError(f"unsupported source format: {source_format!r}")


def _add_segment_descriptions(fields: list[dict]) -> list[dict]:
    """EDIFACT's synthetic "e<i>.c<j>" tags are precise but meaningless
    to a human building a mapping — someone has to know that BGM's
    second element is the invoice number, not the first. Prefixing the
    segment's curated description (the same one parse_edi/validate show)
    at least narrows "which segment is this" even though the exact
    element/component still isn't semantically named — a real EDIFACT
    schema of per-element meanings is out of scope for this pass."""
    for f in fields:
        description = SEGMENT_DESCRIPTIONS.get(f["parent_tag"])
        segment_label = f"{f['parent_tag']} ({description})" if description else f["parent_tag"]
        value = f["value"] or "(empty)"
        f["label"] = f"{segment_label} / {f['tag']}#{f['occurrence']} = {value}"
    return fields


def describe_source_fields(content: str, source_format: str) -> dict:
    """Powers the mapping UI's field pickers: header-scope fields (from
    the whole message, minus line groups) and a line-item *template*
    (fields from the first detected line group only — one representative
    example, since every line group gets mapped the same relative way).
    `source_format` is one of SOURCE_FORMATS. Every field — regardless of
    source format — is addressed uniformly as {parent_tag, tag,
    occurrence}; see ir.py for how EDIFACT's segment/element/component
    shape and XML's real nesting both convert into the same tree."""
    scope = _build_scope_for_source(content, source_format)
    header = ir.flatten_fields(scope.header_leaves, scope.parent_map)
    line_template = (
        ir.flatten_fields(scope.line_group_leaves[0], scope.parent_map) if scope.line_group_leaves else []
    )
    if source_format == "edifact":
        header = _add_segment_descriptions(header)
        line_template = _add_segment_descriptions(line_template)
    return {
        "header": header,
        "line_template": line_template,
        "line_count": len(scope.line_group_leaves),
    }


def _resolve_source_value(resolve_fn, source: dict) -> str | None:
    if source.get("kind") == "constant":
        return source.get("value")
    ref = source.get("ref")
    if not isinstance(ref, dict):
        return None
    return resolve_fn(ref)


def _resolve_values(content: str, source_format: str, field_mappings: list[dict]) -> tuple[dict, list[dict], list[str]]:
    """Format-agnostic resolution: extracts canonical header/line field
    values from any supported source format using the field_mappings'
    addresses. Returns (header_dict, line_dicts, notes)."""
    notes: list[str] = []
    header_entries: list[dict] = []
    line_entries: list[dict] = []
    for m in field_mappings:
        target = m.get("target_field", "")
        if target in HEADER_TARGET_FIELDS:
            header_entries.append(m)
        elif target.startswith("line."):
            subfield = target[len("line.") :]
            if subfield in LINE_SUBFIELDS:
                line_entries.append(m)
            else:
                notes.append(f"{target}: unknown line subfield, skipped")
        else:
            notes.append(f"{target}: unknown target field, skipped")

    try:
        scope = _build_scope_for_source(content, source_format)
    except ValueError as exc:
        notes.append(str(exc))
        return {}, [], notes

    header: dict[str, str] = {}
    for m in header_entries:
        target = m["target_field"]
        value = _resolve_source_value(
            lambda ref: ir.extract_by_ref(scope.header_leaves, scope.parent_map, ref), m.get("source", {})
        )
        if value is None:
            notes.append(f"{target}: source not found in this document, skipped")
            continue
        if target in DATE_FIELDS and _CCYYMMDD.match(value):
            value = f"{value[0:4]}-{value[4:6]}-{value[6:8]}"
        header[target] = value

    line_count = len(scope.line_group_leaves)
    if line_count == 0 and line_entries:
        notes.append("no line-item groups found in this document — 0 lines produced")

    lines: list[dict] = []
    for idx in range(line_count):
        group_leaves = scope.line_group_leaves[idx]
        line: dict[str, str] = {"id": str(idx + 1)}
        for m in line_entries:
            subfield = m["target_field"][len("line.") :]
            value = _resolve_source_value(
                lambda ref: ir.extract_by_ref(group_leaves, scope.parent_map, ref), m.get("source", {})
            )
            if value is None:
                if idx == 0:
                    notes.append(f"line.{subfield}: not found within a line group on this document")
                continue
            line[subfield] = value
        lines.append(line)

    return header, lines, notes


def build_target(header: dict, lines: list[dict], target_format: str) -> tuple[str | None, list[str]]:
    """Format-agnostic target construction from resolved canonical
    header/line dicts. Returns (output_text, notes) — for
    target_format='zugferd' this returns CII XML text; wrapping it into a
    PDF/A-3 is the caller's job (server.py), consistent with how
    generate_synthetic_invoice keeps PDF assembly out of this module."""
    notes: list[str] = []

    required = ["invoice_id", "issue_date", "supplier_name", "customer_name"]
    missing = [f for f in required if not header.get(f)]
    if not lines:
        missing.append("at least one line item")
    if missing:
        notes.append(f"could not build output — missing: {', '.join(missing)}")
        return None, notes

    supported_header = TARGET_SUPPORTED_HEADER_FIELDS.get(target_format, set())
    unsupported_header = sorted(set(header) - supported_header)
    if unsupported_header:
        notes.append(f"not representable for target format {target_format!r}, dropped: {', '.join(unsupported_header)}")

    supported_line = TARGET_SUPPORTED_LINE_FIELDS.get(target_format, set())
    unsupported_line_fields: set[str] = set()
    for line in lines:
        unsupported_line_fields |= set(line) - supported_line - {"id"}
    if unsupported_line_fields:
        notes.append(
            f"line fields not representable for target format {target_format!r}, dropped: "
            f"{', '.join(sorted(unsupported_line_fields))}"
        )

    for idx, line in enumerate(lines):
        line.setdefault("id", str(idx + 1))
        line.setdefault("quantity", "1")
        line.setdefault("unit_code", "EA")
        line.setdefault("line_extension_amount", "0.00")
        line.setdefault("item_name", f"Line {line['id']}")
        line.setdefault("price_amount", line["line_extension_amount"])

    if target_format == "ubl":
        fields = InvoiceFields(
            invoice_id=header["invoice_id"],
            issue_date=header["issue_date"],
            currency=header.get("currency", "EUR"),
            invoice_type_code=header.get("invoice_type_code", "380"),
            supplier_name=header["supplier_name"],
            customer_name=header["customer_name"],
            payable_amount=header.get("payable_amount", "0.00"),
            lines=lines,
            due_date=header.get("due_date"),
            buyer_reference=header.get("buyer_reference"),
            order_reference=header.get("order_reference"),
            contract_reference=header.get("contract_reference"),
            payment_means_code=header.get("payment_means_code"),
            payment_id=header.get("payment_id"),
            payment_terms_note=header.get("payment_terms_note"),
            supplier_street=header.get("supplier_street"),
            supplier_city=header.get("supplier_city"),
            supplier_postal_zone=header.get("supplier_postal_zone"),
            supplier_country_code=header.get("supplier_country_code"),
            supplier_tax_id=header.get("supplier_tax_id"),
            supplier_email=header.get("supplier_email"),
            customer_street=header.get("customer_street"),
            customer_city=header.get("customer_city"),
            customer_postal_zone=header.get("customer_postal_zone"),
            customer_country_code=header.get("customer_country_code"),
            customer_tax_id=header.get("customer_tax_id"),
            customer_email=header.get("customer_email"),
            tax_exclusive_amount=header.get("tax_exclusive_amount"),
            tax_inclusive_amount=header.get("tax_inclusive_amount"),
            tax_total_amount=header.get("tax_total_amount"),
            tax_category_id=header.get("tax_category_id"),
            tax_percent=header.get("tax_percent"),
        )
        return build_invoice_xml(fields), notes

    elif target_format == "edifact":
        text, build_notes = build_edifact_invoic(header, lines)
        return text, notes + build_notes

    elif target_format in ("cii", "zugferd"):
        data_dict, build_notes = canonical_to_cii_data_dict(header, lines)
        return build_cii_xml(data_dict), notes + build_notes

    else:
        notes.append(f"unsupported target format: {target_format!r}")
        return None, notes


@dataclass
class MappingRunResult:
    output: str | None
    notes: list[str] = field(default_factory=list)


def run_mapping(content: str, source_format: str, field_mappings: list[dict], target_format: str) -> MappingRunResult:
    """The any-format-to-any-format entry point behind apply_mapping_profile:
    resolve canonical field values from `content` (in `source_format`)
    using `field_mappings`, then render them as `target_format`."""
    header, lines, resolve_notes = _resolve_values(content, source_format, field_mappings)
    output, build_notes = build_target(header, lines, target_format)
    return MappingRunResult(output=output, notes=resolve_notes + build_notes)
