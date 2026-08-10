"""Hand-rolled EDIFACT tokenizer, structural validator, and writer.

Scope: the segments that actually appear in D01B INVOIC (matches the
Phase 3 RAG corpus). No permissively-licensed EDIFACT parser was worth
depending on for this subset, so this is custom — same call the
architecture doc already made for the TS/Python split.

Deterministic only: this module never asks the LLM anything. Validation
verdicts here are the ground truth handed to validate_with_citation.
"""

from dataclasses import dataclass, field

from mcp_server.ir import Node

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


LINE_GROUP_START_TAG = "LIN"
DETAIL_SECTION_END_TAG = "UNS"  # Section Control: marks detail -> summary transition


def group_segments(segments: list[Segment]) -> tuple[list[Segment], list[list[Segment]]]:
    """Splits a message's segments into header-scope segments and a list of
    line-item groups, using LIN as the group boundary (D01B INVOIC: each
    line item's segment group starts with LIN).

    Header scope is everything *not* inside a line group — both the
    preamble (UNH, BGM, DTM, NAD...) and the trailer (invoice-level MOA
    totals, UNS, CNT, UNT...), since both commonly carry header-level
    invoice fields. This split is what lets a mapping profile generalize:
    a field addressed within "header scope" or "relative to a line group"
    stays correct regardless of how many line items a given document has,
    unlike addressing by absolute segment index.

    The last line group's end is capped at the UNS segment (Section
    Control), which is the standard D01B marker for "detail section ends,
    summary section begins" — without it, trailing header-level segments
    (the invoice total MOA, UNS itself, UNT) would be misattributed to the
    last line item, since a flat tokenizer has no other signal that the
    detail section ended. Messages missing UNS entirely (some legacy
    generators omit it) fall back to end-of-message, which does risk that
    misattribution — a known limitation of not modeling full segment-group
    nesting (SG26 etc.) the way the real spec defines it.
    """
    uns_indices = [i for i, s in enumerate(segments) if s.tag == DETAIL_SECTION_END_TAG]
    detail_end = uns_indices[0] if uns_indices else len(segments)

    line_start_indices = [
        i for i, s in enumerate(segments) if s.tag == LINE_GROUP_START_TAG and i < detail_end
    ]

    line_groups: list[list[Segment]] = []
    in_line_scope = [False] * len(segments)
    for pos, start in enumerate(line_start_indices):
        end = line_start_indices[pos + 1] if pos + 1 < len(line_start_indices) else detail_end
        line_groups.append(segments[start:end])
        for i in range(start, end):
            in_line_scope[i] = True

    header_segments = [s for i, s in enumerate(segments) if not in_line_scope[i]]
    return header_segments, line_groups


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


LINE_GROUP_IR_TAG = "__line__"


def _segment_to_node(seg: Segment) -> Node:
    node = Node(tag=seg.tag)
    for ei, element in enumerate(seg.elements):
        for ci, value in enumerate(element):
            node.children.append(Node(tag=f"e{ei}.c{ci}", value=value))
    return node


def to_ir(result: ParseResult) -> Node:
    """Converts a tokenized EDIFACT message into the unified IR (see
    ir.py): header segments become the tree root's direct children;
    each detected line-item group's segments (see group_segments —
    EDIFACT's line grouping is really a *sibling range* between LIN
    markers, not real nesting) get wrapped into a synthetic __line__
    container node, so ir.build_scope's generic "is this a descendant of
    a line-tagged node" containment check works the same way it does for
    genuinely nested XML source formats — no EDIFACT-specific grouping
    logic needed downstream of this adapter."""
    header_segments, line_groups = group_segments(result.segments)
    root = Node(tag="__root__")
    for seg in header_segments:
        root.children.append(_segment_to_node(seg))
    for group in line_groups:
        group_node = Node(tag=LINE_GROUP_IR_TAG)
        for seg in group:
            group_node.children.append(_segment_to_node(seg))
        root.children.append(group_node)
    return root


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


# EDIFACT header/line fields this builder knows how to place — a subset of
# the full canonical field set (see mapping.py HEADER_TARGET_FIELDS /
# LINE_SUBFIELDS): D01B INVOIC's simplified structure here doesn't have an
# obvious home for full addresses, payment terms/means, or tax breakdown,
# so those are reported as "not representable" rather than guessed at.
EDIFACT_SUPPORTED_HEADER_FIELDS = {"invoice_id", "issue_date", "invoice_type_code", "currency", "payable_amount"}
EDIFACT_SUPPORTED_LINE_FIELDS = {"item_name", "item_description", "quantity", "price_amount", "line_extension_amount"}


def _iso_to_ccyymmdd(value: str) -> str:
    if len(value) == 10 and value[4] == "-" and value[7] == "-":
        return value[0:4] + value[5:7] + value[8:10]
    return value


def build_edifact_invoic(header: dict, lines: list[dict]) -> tuple[str, list[str]]:
    """Builds a D01B INVOIC message from canonical header/line field
    dicts (the same shape mapping.py resolves from any source format).
    Returns (text, notes). Which requested fields have no EDIFACT home
    here is reported centrally by mapping.py's _build_target (computed
    before line dicts get their defaults filled in) rather than by this
    function, so a field the caller never even asked for doesn't show up
    as "dropped"."""
    notes: list[str] = []

    invoice_id = header.get("invoice_id", "")
    issue_date = _iso_to_ccyymmdd(header.get("issue_date", ""))
    invoice_type_code = header.get("invoice_type_code") or "380"
    supplier_name = header.get("supplier_name", "")
    customer_name = header.get("customer_name", "")

    rows: list[tuple[str, list[list[str]]]] = [
        ("UNH", [["1"], ["INVOIC", "D", "01B", "UN"]]),
        ("BGM", [[invoice_type_code], [invoice_id]]),
        ("DTM", [["137", issue_date, "102"]]),
        ("NAD", [["SU"], ["", "", "9"], [""], [supplier_name]]),
        ("NAD", [["BY"], ["", "", "9"], [""], [customer_name]]),
    ]

    total = 0.0
    for i, line in enumerate(lines, start=1):
        item_name = line.get("item_name", f"Line {i}")
        description = line.get("item_description", item_name)
        quantity = line.get("quantity", "1")
        price = line.get("price_amount", "0.00")
        amount_str = line.get("line_extension_amount", "0.00")
        try:
            total += float(amount_str)
        except ValueError:
            pass

        rows += [
            ("LIN", [[str(i)], [""], [item_name, "EN"]]),
            ("IMD", [["F"], [""], ["", "", "", description]]),
            ("QTY", [["47", str(quantity)]]),
            ("PRI", [["AAA", str(price)]]),
            ("MOA", [["203", str(amount_str)]]),
        ]

    rows.append(("UNS", [["S"]]))
    payable_amount = header.get("payable_amount") or f"{total:.2f}"
    rows.append(("MOA", [["77", str(payable_amount)]]))
    body_count = len(rows) + 1
    rows.append(("UNT", [[str(body_count)], ["1"]]))

    return write_segments(rows), notes
