"""UBL 2.1 Invoice: real XSD schema validation (via `xmlschema`) plus a
document builder used by both map_format/apply_mapping_profile and
generate_synthetic_invoice.

Validation here is the deterministic ground truth — see
docs/threat-model.md T2: "Validation truth never comes from the LLM."

Element ordering below was verified against the actual compiled schema
(xmlschema's `.content.iter_elements()` on each complex type), not
guessed — UBL's XSD uses strict `xsd:sequence` ordering, so a field in
the wrong position fails validation with a confusing "wrong element"
error rather than a useful one. Only elements with a value are emitted;
everything here is optional except the handful of UBL-mandated fields
InvoiceFields itself requires.

Scope note: this covers the header/line fields most invoices need
(dates, references, payment terms/means, full addresses, tax IDs, tax
totals, line-level tax category) — not the complete UBL Invoice schema,
which runs to hundreds of optional elements. Tax scheme is hardcoded to
"VAT" (the near-universal EU convention) rather than user-configurable,
and only XSD structural validity is checked here, not Schematron-level
business-rule validation (e.g. "taxes sum correctly") — consistent with
how validate_with_citation is scoped elsewhere in this service.
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

TAX_SCHEME_ID = "VAT"


@dataclass
class Finding:
    level: str
    code: str
    message: str
    path: str | None = None


@dataclass
class InvoiceFields:
    # Required
    invoice_id: str
    issue_date: str  # YYYY-MM-DD
    currency: str
    invoice_type_code: str
    supplier_name: str
    customer_name: str
    payable_amount: str
    lines: list[dict] = field(default_factory=list)
    # each line dict may carry: id, quantity, unit_code, line_extension_amount,
    # item_name, price_amount, item_description, buyers_item_id,
    # sellers_item_id, tax_category_id, tax_percent

    # Optional header fields
    due_date: str | None = None
    buyer_reference: str | None = None
    order_reference: str | None = None
    contract_reference: str | None = None
    payment_means_code: str | None = None
    payment_id: str | None = None
    payment_terms_note: str | None = None

    supplier_street: str | None = None
    supplier_city: str | None = None
    supplier_postal_zone: str | None = None
    supplier_country_code: str | None = None
    supplier_tax_id: str | None = None
    supplier_email: str | None = None

    customer_street: str | None = None
    customer_city: str | None = None
    customer_postal_zone: str | None = None
    customer_country_code: str | None = None
    customer_tax_id: str | None = None
    customer_email: str | None = None

    tax_exclusive_amount: str | None = None
    tax_inclusive_amount: str | None = None
    tax_total_amount: str | None = None
    tax_category_id: str | None = None
    tax_percent: str | None = None


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


def _party(CAC, CBC, *, name, street, city, postal_zone, country_code, tax_id, email):
    """Builds a cac:Party in the schema's required child order:
    PartyName -> PostalAddress -> PartyTaxScheme -> Contact."""
    children = [CAC.PartyName(CBC.Name(name))]

    address_children = [
        *([CBC.StreetName(street)] if street else []),
        *([CBC.CityName(city)] if city else []),
        *([CBC.PostalZone(postal_zone)] if postal_zone else []),
        *([CAC.Country(CBC.IdentificationCode(country_code))] if country_code else []),
    ]
    if address_children:
        children.append(CAC.PostalAddress(*address_children))

    if tax_id:
        children.append(CAC.PartyTaxScheme(CBC.CompanyID(tax_id), CAC.TaxScheme(CBC.ID(TAX_SCHEME_ID))))

    if email:
        children.append(CAC.Contact(CBC.ElectronicMail(email)))

    return CAC.Party(*children)


def build_invoice_xml(f: InvoiceFields) -> str:
    E = ElementMaker(namespace=NSMAP[None], nsmap=NSMAP)
    CAC = ElementMaker(namespace=NSMAP["cac"])
    CBC = ElementMaker(namespace=NSMAP["cbc"])

    lines = []
    for i, line in enumerate(f.lines, start=1):
        item_children = [
            *([CBC.Description(line["item_description"])] if line.get("item_description") else []),
            CBC.Name(line["item_name"]),
            *(
                [CAC.BuyersItemIdentification(CBC.ID(line["buyers_item_id"]))]
                if line.get("buyers_item_id")
                else []
            ),
            *(
                [CAC.SellersItemIdentification(CBC.ID(line["sellers_item_id"]))]
                if line.get("sellers_item_id")
                else []
            ),
        ]
        if line.get("tax_category_id") or line.get("tax_percent"):
            tax_cat_children = [
                *([CBC.ID(line["tax_category_id"])] if line.get("tax_category_id") else []),
                *([CBC.Percent(str(line["tax_percent"]))] if line.get("tax_percent") else []),
                CAC.TaxScheme(CBC.ID(TAX_SCHEME_ID)),
            ]
            item_children.append(CAC.ClassifiedTaxCategory(*tax_cat_children))

        lines.append(
            CAC.InvoiceLine(
                CBC.ID(str(line.get("id", i))),
                CBC.InvoicedQuantity(str(line["quantity"]), unitCode=line.get("unit_code", "EA")),
                CBC.LineExtensionAmount(str(line["line_extension_amount"]), currencyID=f.currency),
                CAC.Item(*item_children),
                CAC.Price(CBC.PriceAmount(str(line["price_amount"]), currencyID=f.currency)),
            )
        )

    supplier = _party(
        CAC,
        CBC,
        name=f.supplier_name,
        street=f.supplier_street,
        city=f.supplier_city,
        postal_zone=f.supplier_postal_zone,
        country_code=f.supplier_country_code,
        tax_id=f.supplier_tax_id,
        email=f.supplier_email,
    )
    customer = _party(
        CAC,
        CBC,
        name=f.customer_name,
        street=f.customer_street,
        city=f.customer_city,
        postal_zone=f.customer_postal_zone,
        country_code=f.customer_country_code,
        tax_id=f.customer_tax_id,
        email=f.customer_email,
    )

    order_and_refs = [
        *([CAC.OrderReference(CBC.ID(f.order_reference))] if f.order_reference else []),
        *([CAC.ContractDocumentReference(CBC.ID(f.contract_reference))] if f.contract_reference else []),
    ]

    payment_means = (
        [
            CAC.PaymentMeans(
                CBC.PaymentMeansCode(f.payment_means_code or "1"),
                *([CBC.PaymentID(f.payment_id)] if f.payment_id else []),
            )
        ]
        if f.payment_means_code or f.payment_id
        else []
    )
    payment_terms = [CAC.PaymentTerms(CBC.Note(f.payment_terms_note))] if f.payment_terms_note else []

    tax_total = []
    if f.tax_total_amount:
        subtotal_children = [
            *([CBC.TaxableAmount(f.tax_exclusive_amount, currencyID=f.currency)] if f.tax_exclusive_amount else []),
            CBC.TaxAmount(f.tax_total_amount, currencyID=f.currency),
            CAC.TaxCategory(
                *[
                    *([CBC.ID(f.tax_category_id)] if f.tax_category_id else []),
                    *([CBC.Percent(f.tax_percent)] if f.tax_percent else []),
                    CAC.TaxScheme(CBC.ID(TAX_SCHEME_ID)),
                ]
            ),
        ]
        has_subtotal_detail = f.tax_category_id or f.tax_percent or f.tax_exclusive_amount
        tax_total.append(
            CAC.TaxTotal(
                CBC.TaxAmount(f.tax_total_amount, currencyID=f.currency),
                *([CAC.TaxSubtotal(*subtotal_children)] if has_subtotal_detail else []),
            )
        )

    monetary_total_children = [
        *([CBC.TaxExclusiveAmount(f.tax_exclusive_amount, currencyID=f.currency)] if f.tax_exclusive_amount else []),
        *([CBC.TaxInclusiveAmount(f.tax_inclusive_amount, currencyID=f.currency)] if f.tax_inclusive_amount else []),
        CBC.PayableAmount(f.payable_amount, currencyID=f.currency),
    ]

    invoice = E.Invoice(
        CBC.ID(f.invoice_id),
        CBC.IssueDate(f.issue_date),
        *([CBC.DueDate(f.due_date)] if f.due_date else []),
        CBC.InvoiceTypeCode(f.invoice_type_code),
        CBC.DocumentCurrencyCode(f.currency),
        *([CBC.BuyerReference(f.buyer_reference)] if f.buyer_reference else []),
        *order_and_refs,
        CAC.AccountingSupplierParty(supplier),
        CAC.AccountingCustomerParty(customer),
        *payment_means,
        *payment_terms,
        *tax_total,
        CAC.LegalMonetaryTotal(*monetary_total_children),
        *lines,
    )
    return etree.tostring(invoice, pretty_print=True, xml_declaration=True, encoding="UTF-8").decode()
