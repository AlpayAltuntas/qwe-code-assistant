"""Turns staged/promoted spec documents into (section, text) chunks.

Formats handled: EDIFACT segment-clarification HTML pages
(parse_edifact_html) and XSD schemas with per-element documentation
(parse_xsd_documentation — generic enough to cover both UBL's
CCTS-structured annotations and CII's plain xsd:documentation labels,
so Phase 5's ZUGFeRD/CII corpus addition needed no new parser). Adding a
genuinely new document shape means adding one more `parse_*` function
and a dispatch entry in `parse_document` — the rest of the ingestion
pipeline is format-agnostic.
"""

import re
from pathlib import Path

from bs4 import BeautifulSoup
from lxml import etree

XSD_NS = "http://www.w3.org/2001/XMLSchema"
CCTS_NS = "urn:un:unece:uncefact:documentation:2"


def _local(tag: str) -> str:
    return etree.QName(tag).localname


def chunk_text(text: str, max_chars: int = 900, overlap: int = 150) -> list[str]:
    """Greedy paragraph-packing chunker with a trailing overlap for context."""
    text = text.strip()
    if len(text) <= max_chars:
        return [text] if text else []

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        paragraphs = [text]

    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) > max_chars and current:
            chunks.append(current)
            current = current[-overlap:] + "\n\n" + para if overlap else para
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def parse_edifact_html(path: Path) -> list[tuple[str, str]]:
    """Extract per-segment narrative descriptions from a UNTDID-style
    message page (e.g. the D01B INVOIC segment clarifications)."""
    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="ignore"), "html.parser")

    heading = soup.find(
        lambda tag: tag.name == "h3" and "Message description" in tag.get_text()
    )
    if heading is None:
        return []
    container = heading.find_next("div")
    if container is None:
        return []
    text = container.get_text("\n", strip=True)

    segment_header = re.compile(r"(?m)^([A-Z]{2,3}\d?)\s+[MC]\(\d+\)\s*:\s")
    matches = list(segment_header.finditer(text))
    if not matches:
        return [("overview", text)] if text else []

    sections: list[tuple[str, str]] = []
    if matches[0].start() > 0:
        lead = text[: matches[0].start()].strip()
        if lead:
            sections.append(("overview", lead))

    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append((match.group(1), text[start:end].strip()))

    return sections


def _ccts_fields(annotation_el) -> dict[str, str]:
    component = annotation_el.find(f".//{{{CCTS_NS}}}Component")
    if component is None:
        return {}
    fields: dict[str, str] = {}
    for child in component:
        value = (child.text or "").strip()
        if value:
            fields[_local(child.tag)] = value
    return fields


def parse_xsd_documentation(path: Path) -> list[tuple[str, str]]:
    """Extract per-element documentation (CCTS-structured where present —
    UBL's style; plain xsd:documentation otherwise — CII's style) plus
    name/type facts for elements that carry no prose documentation at
    all. Generic across schema families: used for both UBL and CII XSDs."""
    tree = etree.parse(str(path))
    root = tree.getroot()
    ns = {"xsd": XSD_NS}

    results: list[tuple[str, str]] = []
    documented_names: set[str] = set()

    for annotation in root.findall(".//xsd:annotation", ns):
        parent = annotation.getparent()
        if _local(parent.tag) != "element":
            continue
        name = parent.get("name") or parent.get("ref") or ""
        if not name:
            continue

        ccts = _ccts_fields(annotation)
        if ccts:
            text = " | ".join(f"{key}: {value}" for key, value in ccts.items())
        else:
            doc_nodes = annotation.findall("xsd:documentation", ns)
            node_texts = [" ".join(" ".join(node.itertext()).split()) for node in doc_nodes]
            text = " ".join(t for t in node_texts if t)

        if text:
            results.append((name, text))
            documented_names.add(name)

    for element in root.findall(".//xsd:element", ns):
        name = element.get("name") or element.get("ref")
        type_ = element.get("type")
        if name and type_ and name not in documented_names and element.find("xsd:annotation", ns) is None:
            results.append((name, f"{name} is declared with XSD type {type_}."))
            documented_names.add(name)

    return results


def parse_document(path: Path) -> list[tuple[str, str]]:
    """Dispatch by extension. Returns (section, chunk_text) pairs, already
    generically re-chunked where an individual section ran oversized."""
    if path.suffix in (".htm", ".html"):
        sections = parse_edifact_html(path)
    elif path.suffix == ".xsd":
        sections = parse_xsd_documentation(path)
    else:
        raise ValueError(f"no parser registered for extension {path.suffix!r} ({path})")

    chunks: list[tuple[str, str]] = []
    for section, text in sections:
        pieces = chunk_text(text)
        for i, piece in enumerate(pieces):
            label = section if len(pieces) == 1 else f"{section}#{i}"
            chunks.append((label, piece))
    return chunks
