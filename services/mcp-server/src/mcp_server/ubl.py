"""UBL 2.1 Invoice: real XSD schema validation (via `xmlschema`) plus a
minimal-but-valid document builder used by both map_format and
generate_synthetic_invoice.

Validation here is the deterministic ground truth — see
docs/threat-model.md T2: "Validation truth never comes from the LLM."
"""

from dataclasses import dataclass, field
from functools import lru_cache

import defusedxml.ElementTree as safe_ET
import xmlschema
from lxml import etree
from lxml.builder import ElementMaker

from mcp_server.config import UBL_INVOICE_XSD

NSMAP = {
    None: "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
}


@dataclass
class Finding:
    level: str
    code: str
    message: str
    path: str | None = None


@dataclass
class InvoiceFields:
    invoice_id: str
    issue_date: str  # YYYY-MM-DD
    currency: str
    invoice_type_code: str
    supplier_name: str
    customer_name: str
    payable_amount: str
    lines: list[dict] = field(default_factory=list)
    # each line: {id, quantity, unit_code, line_extension_amount, item_name, price_amount}


@lru_cache(maxsize=1)
def _schema() -> xmlschema.XMLSchema:
    return xmlschema.XMLSchema(str(UBL_INVOICE_XSD))


def validate(xml_text: str) -> list[Finding]:
    """Well-formedness first (via defusedxml, hardened against XXE/entity
    expansion per docs/threat-model.md D1), then real XSD validation —
    against that *same* safely-parsed tree, not a second raw-text parse,
    so the hardening actually covers the parse that gets used."""
    try:
        root = safe_ET.fromstring(xml_text)
    except Exception as exc:  # noqa: BLE001 - surfaced as a Finding, not raised
        return [Finding("error", "not-well-formed", f"XML is not well-formed: {exc}")]

    errors = list(_schema().iter_errors(root))
    if not errors:
        return [Finding("info", "ok", "schema validation passed (UBL 2.1 Invoice)")]

    return [
        Finding("error", "schema-violation", e.reason or str(e), getattr(e, "path", None))
        for e in errors
    ]


def build_invoice_xml(f: InvoiceFields) -> str:
    E = ElementMaker(namespace=NSMAP[None], nsmap=NSMAP)
    CAC = ElementMaker(namespace=NSMAP["cac"])
    CBC = ElementMaker(namespace=NSMAP["cbc"])

    lines = []
    for i, line in enumerate(f.lines, start=1):
        lines.append(
            CAC.InvoiceLine(
                CBC.ID(str(line.get("id", i))),
                CBC.InvoicedQuantity(str(line["quantity"]), unitCode=line.get("unit_code", "EA")),
                CBC.LineExtensionAmount(str(line["line_extension_amount"]), currencyID=f.currency),
                CAC.Item(CBC.Name(line["item_name"])),
                CAC.Price(CBC.PriceAmount(str(line["price_amount"]), currencyID=f.currency)),
            )
        )

    invoice = E.Invoice(
        CBC.ID(f.invoice_id),
        CBC.IssueDate(f.issue_date),
        CBC.InvoiceTypeCode(f.invoice_type_code),
        CBC.DocumentCurrencyCode(f.currency),
        CAC.AccountingSupplierParty(CAC.Party(CAC.PartyName(CBC.Name(f.supplier_name)))),
        CAC.AccountingCustomerParty(CAC.Party(CAC.PartyName(CBC.Name(f.customer_name)))),
        CAC.LegalMonetaryTotal(CBC.PayableAmount(f.payable_amount, currencyID=f.currency)),
        *lines,
    )
    return etree.tostring(invoice, pretty_print=True, xml_declaration=True, encoding="UTF-8").decode()
