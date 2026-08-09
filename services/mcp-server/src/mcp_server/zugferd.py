"""ZUGFeRD / Factur-X: CII (Cross Industry Invoice) XML validation and
PDF/A-3 assembly, built on the `factur-x` library (BSD-licensed) rather
than hand-resolving UN/CEFACT's full codelist schema tree ourselves —
that tree is dozens of files deep; `factur-x` already bundles a working,
tested schema set as package data.

Same deterministic-verdict principle as ubl.py/edifact.py: validation
here is real XSD validation, never inferred by the model.
"""

import io

from facturx import generate_cii_xml, generate_from_binary, get_xml_from_pdf
from facturx.facturx import xml_check_xsd
from lxml import etree
from pypdf import PdfWriter

from mcp_server.ubl import Finding

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
