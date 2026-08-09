"""Hand-rolled EDIFACT tokenizer, structural validator, and writer.

Scope: the segments that actually appear in D01B INVOIC (matches the
Phase 3 RAG corpus). No permissively-licensed EDIFACT parser was worth
depending on for this subset, so this is custom — same call the
architecture doc already made for the TS/Python split.

Deterministic only: this module never asks the LLM anything. Validation
verdicts here are the ground truth handed to validate_with_citation.
"""

from dataclasses import dataclass, field

DEFAULT_COMPONENT_SEP = ":"
DEFAULT_ELEMENT_SEP = "+"
DEFAULT_RELEASE_CHAR = "?"
DEFAULT_SEGMENT_TERMINATOR = "'"

# Curated subset of D01B segment tags relevant to INVOIC — not exhaustive.
# For the authoritative full text, see the Phase 3 RAG corpus
# (services/router) via validate_with_citation's citations.
SEGMENT_DESCRIPTIONS: dict[str, str] = {
    "UNB": "Interchange header",
    "UNH": "Message header",
    "BGM": "Beginning of message",
    "DTM": "Date/time/period",
    "PAI": "Payment instructions",
    "ALI": "Additional information",
    "IMD": "Item description",
    "FTX": "Free text",
    "LOC": "Place/location identification",
    "GIS": "General indicator",
    "DGS": "Dangerous goods",
    "GIR": "Related identification numbers",
    "RFF": "Reference",
    "NAD": "Name and address",
    "FII": "Financial institution information",
    "SG": "Segment group",
    "CTA": "Contact information",
    "COM": "Communication contact",
    "TAX": "Duty/tax/fee details",
    "MOA": "Monetary amount",
    "PAT": "Payment terms basis",
    "PCD": "Percentage details",
    "TDT": "Details of transport",
    "TOD": "Terms of delivery or transport",
    "LIN": "Line item",
    "PIA": "Additional product id",
    "QTY": "Quantity",
    "ALC": "Allowance or charge",
    "CUX": "Currencies",
    "PRI": "Price details",
    "UNS": "Section control",
    "CNT": "Control total",
    "UNT": "Message trailer",
    "UNZ": "Interchange trailer",
}


@dataclass
class Segment:
    tag: str
    elements: list[list[str]]
    raw: str


@dataclass
class Finding:
    level: str  # "error" | "warning" | "info"
    code: str
    message: str
    segment_index: int | None = None


@dataclass
class ParseResult:
    segments: list[Segment] = field(default_factory=list)
    separators: dict[str, str] = field(default_factory=dict)


def _split_respecting_release(s: str, sep: str, release: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == release and i + 1 < len(s):
            current.append(s[i + 1])
            i += 2
            continue
        if ch == sep:
            parts.append("".join(current))
            current = []
            i += 1
            continue
        current.append(ch)
        i += 1
    parts.append("".join(current))
    return parts


def _escape(value: str, separators: dict[str, str]) -> str:
    release = separators["release"]
    special = {separators["segment_terminator"], separators["element_sep"], separators["component_sep"], release}
    out = []
    for ch in value:
        if ch in special:
            out.append(release)
        out.append(ch)
    return "".join(out)


def tokenize(text: str) -> ParseResult:
    separators = {
        "component_sep": DEFAULT_COMPONENT_SEP,
        "element_sep": DEFAULT_ELEMENT_SEP,
        "release": DEFAULT_RELEASE_CHAR,
        "segment_terminator": DEFAULT_SEGMENT_TERMINATOR,
    }

    body = text
    if text.lstrip().startswith("UNA"):
        stripped = text.lstrip()
        marker = stripped[3:9]
        if len(marker) == 6:
            separators["component_sep"] = marker[0]
            separators["element_sep"] = marker[1]
            separators["release"] = marker[3]
            separators["segment_terminator"] = marker[5]
        after_una = stripped[9:]
        body = after_una.lstrip(separators["segment_terminator"]) if after_una.startswith(
            separators["segment_terminator"]
        ) else after_una

    body = body.replace("\r\n", "").replace("\n", "").replace("\r", "")

    raw_segments = _split_respecting_release(body, separators["segment_terminator"], separators["release"])

    segments: list[Segment] = []
    for raw in raw_segments:
        raw = raw.strip()
        if not raw:
            continue
        parts = _split_respecting_release(raw, separators["element_sep"], separators["release"])
        tag = parts[0]
        elements = [
            _split_respecting_release(p, separators["component_sep"], separators["release"])
            for p in parts[1:]
        ]
        segments.append(Segment(tag=tag, elements=elements, raw=raw))

    return ParseResult(segments=segments, separators=separators)


def validate_structure(result: ParseResult) -> list[Finding]:
    findings: list[Finding] = []
    segments = result.segments

    for i, seg in enumerate(segments):
        if not (2 <= len(seg.tag) <= 3 and seg.tag.isalpha() and seg.tag.isupper()):
            findings.append(
                Finding("error", "bad-tag", f"segment {i}: {seg.tag!r} is not a valid segment tag", i)
            )
        elif seg.tag not in SEGMENT_DESCRIPTIONS and seg.tag not in ("UNA",):
            findings.append(
                Finding(
                    "info",
                    "unknown-tag",
                    f"segment {i}: tag {seg.tag!r} isn't in the curated description set "
                    "(not necessarily invalid — see citations for the authoritative spec)",
                    i,
                )
            )

    unh_indices = [i for i, s in enumerate(segments) if s.tag == "UNH"]
    unt_indices = [i for i, s in enumerate(segments) if s.tag == "UNT"]

    if not unh_indices:
        findings.append(Finding("error", "missing-unh", "no UNH (message header) segment found"))
    if not unt_indices:
        findings.append(Finding("error", "missing-unt", "no UNT (message trailer) segment found"))

    for unh_i, unt_i in zip(unh_indices, unt_indices):
        unh, unt = segments[unh_i], segments[unt_i]
        unh_ref = unh.elements[0][0] if unh.elements else None
        unt_ref = unt.elements[1][0] if len(unt.elements) > 1 else None
        if unh_ref != unt_ref:
            findings.append(
                Finding(
                    "error",
                    "control-ref-mismatch",
                    f"UNH message reference {unh_ref!r} does not match UNT reference {unt_ref!r}",
                    unh_i,
                )
            )
        expected_count = unt_i - unh_i + 1
        declared_count = unt.elements[0][0] if unt.elements else None
        if declared_count is not None and str(declared_count) != str(expected_count):
            findings.append(
                Finding(
                    "error",
                    "segment-count-mismatch",
                    f"UNT declares {declared_count} segments but {expected_count} were found "
                    f"between UNH and UNT",
                    unt_i,
                )
            )

    if unh_indices:
        unh = segments[unh_indices[0]]
        msg_type = unh.elements[1][0] if len(unh.elements) > 1 and unh.elements[1] else None
        if msg_type and msg_type != "INVOIC":
            findings.append(
                Finding(
                    "warning",
                    "unexpected-message-type",
                    f"message type is {msg_type!r}, this toolset targets INVOIC",
                )
            )

    bgm_present = any(s.tag == "BGM" for s in segments)
    if unh_indices and not bgm_present:
        findings.append(Finding("error", "missing-bgm", "no BGM (beginning of message) segment found"))

    if not findings:
        findings.append(Finding("info", "ok", "structural checks passed"))

    return findings


def write_segments(rows: list[tuple[str, list[list[str]]]], separators: dict[str, str] | None = None) -> str:
    """Inverse of tokenize: serialize (tag, elements) rows to EDIFACT text."""
    sep = separators or {
        "component_sep": DEFAULT_COMPONENT_SEP,
        "element_sep": DEFAULT_ELEMENT_SEP,
        "release": DEFAULT_RELEASE_CHAR,
        "segment_terminator": DEFAULT_SEGMENT_TERMINATOR,
    }
    lines = []
    for tag, elements in rows:
        element_strs = [
            sep["component_sep"].join(_escape(c, sep) for c in element) for element in elements
        ]
        lines.append(sep["element_sep"].join([tag, *element_strs]) + sep["segment_terminator"])
    return "\n".join(lines)
