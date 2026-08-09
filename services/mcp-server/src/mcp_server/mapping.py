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

from dataclasses import dataclass, field

from mcp_server.edifact import ParseResult, Segment
from mcp_server.ubl import InvoiceFields

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
