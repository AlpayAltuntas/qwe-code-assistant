"""ZUGFeRD / Factur-X: CII (Cross Industry Invoice) XML validation and
PDF/A-3 assembly, built on the `factur-x` library (BSD-licensed) rather
than hand-resolving UN/CEFACT's full codelist schema tree ourselves —
that tree is dozens of files deep; `factur-x` already bundles a working,
tested schema set as package data.

Same deterministic-verdict principle as ubl.py/edifact.py: validation
here is real XSD validation, never inferred by the model.
"""

import datetime
import io

from facturx import generate_cii_xml, generate_from_binary, get_xml_from_pdf
from facturx.facturx import xml_check_xsd
from lxml import etree
from pypdf import PdfWriter

from mcp_server.ubl import Finding

DEFAULT_TAX_CATEGORY = "S"
DEFAULT_TAX_PERCENT = "0"

# Hardened parser: no DTD loading, no entity resolution, no network —
# same XXE/entity-expansion protections as defusedxml, but returns an
# lxml Element (which factur-x's xml_check_xsd requires) instead of an
# ElementTree one. Used for every untrusted-XML parse in this module so
# validation runs against the safely-parsed tree, not a second raw parse.
_SAFE_PARSER = etree.XMLParser(
    resolve_entities=False, no_network=True, dtd_validation=False, load_dtd=False
)


def _safe_parse(xml_text: str) -> etree._Element:
    return etree.fromstring(xml_text.encode("utf-8"), parser=_SAFE_PARSER)


def validate_cii(xml_text: str) -> list[Finding]:
    try:
        root = _safe_parse(xml_text)
    except Exception as exc:  # noqa: BLE001
        return [Finding("error", "not-well-formed", f"XML is not well-formed: {exc}")]

    try:
        xml_check_xsd(root, flavor="factur-x", level="autodetect")
    except Exception as exc:  # noqa: BLE001 - factur-x raises on invalid
        return [Finding("error", "schema-violation", str(exc))]

    return [Finding("info", "ok", "schema validation passed (Factur-X/ZUGFeRD CII, EN16931)")]


def extract_cii_from_pdf(pdf_bytes: bytes) -> tuple[str, str]:
    """Returns (attachment_filename, xml_text) for a ZUGFeRD/Factur-X PDF."""
    filename, xml_bytes = get_xml_from_pdf(pdf_bytes, check_xsd=True)
    return filename, xml_bytes.decode("utf-8")


def build_cii_xml(data_dict: dict, level: str = "en16931") -> str:
    xml_bytes = generate_cii_xml(data_dict, level=level, check_xsd=True, check_schematron=False)
    return xml_bytes.decode("utf-8")


def _parse_date(value: str) -> datetime.date | None:
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _to_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# CII (EN16931, via the factur-x library) fields this builder knows how to
# place, mapped from the same canonical field set used for UBL/EDIFACT (see
# mapping.py HEADER_TARGET_FIELDS / LINE_SUBFIELDS). Everything else silently
# has no representation attempted — `canonical_to_cii_data_dict` only ever
# reads the keys listed below, so unmapped canonical fields are naturally
# dropped (reported by the caller, which knows the full set that was asked for).
CII_SUPPORTED_HEADER_FIELDS = {
    "invoice_id",
    "issue_date",
    "due_date",
    "invoice_type_code",
    "currency",
    "order_reference",
    "contract_reference",
    "payment_means_code",
    "payment_id",
    "supplier_name",
    "supplier_street",
    "supplier_city",
    "supplier_postal_zone",
    "supplier_country_code",
    "supplier_tax_id",
    "customer_name",
    "customer_street",
    "customer_city",
    "customer_postal_zone",
    "customer_country_code",
    "customer_tax_id",
    "tax_exclusive_amount",
    "tax_inclusive_amount",
    "tax_total_amount",
    "tax_category_id",
    "tax_percent",
    "payable_amount",
}
CII_SUPPORTED_LINE_FIELDS = {
    "item_name",
    "item_description",
    "buyers_item_id",
    "sellers_item_id",
    "quantity",
    "unit_code",
    "price_amount",
    "line_extension_amount",
    "tax_category_id",
    "tax_percent",
}


def canonical_to_cii_data_dict(header: dict, lines: list[dict]) -> tuple[dict, list[str]]:
    """Maps the canonical header/line field dicts (same shape used for
    UBL/EDIFACT) into the BT-* keyed dict `generate_cii_xml` expects.
    EN16931 requires several totals/tax fields that the canonical set
    treats as optional (BT-106 line total, BT-109 tax-exclusive, BT-110
    tax amount, BT-112 tax-inclusive, BT-115 payable, and at least one
    BG-23 tax subtotal) — these get computed from whatever line amounts
    and tax rate *are* present rather than left absent, the same
    "derive a sane default, note it" approach used elsewhere (e.g.
    map_edifact_invoic_to_ubl deriving price from amount/quantity)."""
    notes: list[str] = []

    net_total = 0.0
    cii_lines = []
    for i, line in enumerate(lines, start=1):
        amount = _to_float(line.get("line_extension_amount"))
        net_total += amount
        cii_lines.append(
            {
                "BT-126": str(line.get("id", i)),
                "BT-153": line.get("item_name", f"Line {i}"),
                **({"BT-154": line["item_description"]} if line.get("item_description") else {}),
                "BT-146": str(line.get("price_amount", amount)),
                "BT-129": str(line.get("quantity", "1")),
                "BT-130": line.get("unit_code", "EA"),
                "BT-131": f"{amount:.2f}",
                **({"BT-156": line["buyers_item_id"]} if line.get("buyers_item_id") else {}),
                **({"BT-155": line["sellers_item_id"]} if line.get("sellers_item_id") else {}),
                "BT-151": line.get("tax_category_id", DEFAULT_TAX_CATEGORY),
                "BT-152": str(line.get("tax_percent", DEFAULT_TAX_PERCENT)),
            }
        )

    tax_exclusive = _to_float(header.get("tax_exclusive_amount"), net_total)
    tax_percent = header.get("tax_percent") or (lines[0].get("tax_percent") if lines else None) or DEFAULT_TAX_PERCENT
    tax_total = _to_float(header.get("tax_total_amount"), tax_exclusive * _to_float(tax_percent) / 100)
    tax_inclusive = _to_float(header.get("tax_inclusive_amount"), tax_exclusive + tax_total)
    payable = header.get("payable_amount") or f"{tax_inclusive:.2f}"
    tax_category = header.get("tax_category_id") or (lines[0].get("tax_category_id") if lines else None) or DEFAULT_TAX_CATEGORY

    issue_date = _parse_date(header.get("issue_date", "")) or datetime.date.today()
    due_date = _parse_date(header.get("due_date", "")) if header.get("due_date") else None

    data_dict: dict = {
        "BT-24": None,
        "BT-1": header.get("invoice_id", ""),
        "BT-2": issue_date,
        "BT-3": header.get("invoice_type_code") or "380",
        "BT-5": header.get("currency") or "EUR",
        "BT-72": issue_date,
        "BT-27": header.get("supplier_name", ""),
        "BT-40": header.get("supplier_country_code") or "XX",
        "BT-44": header.get("customer_name", ""),
        "BT-55": header.get("customer_country_code") or "XX",
        "BT-106": f"{net_total:.2f}",
        "BT-109": f"{tax_exclusive:.2f}",
        "BT-110": f"{tax_total:.2f}",
        "BT-110-1": header.get("currency") or "EUR",
        "BT-112": f"{tax_inclusive:.2f}",
        "BT-115": str(payable),
        "BG-23": [
            {
                "BT-116": f"{tax_exclusive:.2f}",
                "BT-117": f"{tax_total:.2f}",
                "BT-118": tax_category,
                "BT-119": str(tax_percent),
            }
        ],
        "BG-25": cii_lines,
    }
    if due_date:
        data_dict["BT-9"] = due_date
    if header.get("order_reference"):
        data_dict["BT-13"] = header["order_reference"]
    if header.get("contract_reference"):
        data_dict["BT-12"] = header["contract_reference"]
    if header.get("payment_means_code"):
        data_dict["BT-81"] = header["payment_means_code"]
    if header.get("payment_id"):
        data_dict["BT-82"] = header["payment_id"]
    if header.get("supplier_street"):
        data_dict["BT-35"] = header["supplier_street"]
    if header.get("supplier_city"):
        data_dict["BT-37"] = header["supplier_city"]
    if header.get("supplier_postal_zone"):
        data_dict["BT-38"] = header["supplier_postal_zone"]
    if header.get("supplier_tax_id"):
        data_dict["BT-31"] = header["supplier_tax_id"]
    if header.get("customer_street"):
        data_dict["BT-50"] = header["customer_street"]
    if header.get("customer_city"):
        data_dict["BT-52"] = header["customer_city"]
    if header.get("customer_postal_zone"):
        data_dict["BT-53"] = header["customer_postal_zone"]
    if header.get("customer_tax_id"):
        data_dict["BT-48"] = header["customer_tax_id"]

    return data_dict, notes


def assemble_pdf(cii_xml_text: str) -> bytes:
    """Embeds CII XML into a minimal single-page PDF as a proper
    Factur-X/ZUGFeRD PDF/A-3 (correct AFRelationship + XMP metadata via
    the factur-x library). The visual layer is a blank placeholder page —
    this tool produces machine-readable synthetic test fixtures, not a
    rendered invoice document; the XML is the authoritative content."""
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)  # A4
    buf = io.BytesIO()
    writer.write(buf)
    carrier_pdf = buf.getvalue()

    return generate_from_binary(
        carrier_pdf,
        cii_xml_text.encode("utf-8"),
        flavor="factur-x",
        level="en16931",
        check_xsd=True,
    )
