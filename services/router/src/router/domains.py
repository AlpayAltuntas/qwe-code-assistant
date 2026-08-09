"""Domain registry for the router cascade.

Adding a second domain later means registering a new DomainConfig here
— the cascade loop in cascade.py is domain-agnostic and never hardcodes
"edi". See docs/architecture.md "Router design".
"""

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class DomainConfig:
    id: str
    display_name: str
    # Regexes distinctive enough that a single match is a strong signal
    # on its own (e.g. an EDIFACT segment token like "BGM+380").
    strong_patterns: list[re.Pattern] = field(default_factory=list)
    # Plain keywords that are suggestive but not conclusive alone —
    # trigger Stage 1 (embedding similarity) rather than an immediate
    # activation.
    weak_keywords: list[str] = field(default_factory=list)
    vector_collection: str = ""
    stage1_similarity_threshold: float = 0.55
    stage2_confidence_threshold: float = 0.65
    toolset: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Word-boundary compiled forms of weak_keywords, built once so
        # cascade._stage0 never does a naive substring `in` check (which
        # would false-match "edi" inside "edit"/"immediately", "ubl"
        # inside "public"/"republic", etc.)
        object.__setattr__(
            self,
            "_weak_keyword_patterns",
            [
                (kw, re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE))
                for kw in self.weak_keywords
            ],
        )


EDI_STRONG_PATTERNS = [
    re.compile(pattern, re.MULTILINE)
    for pattern in [
        r"\bUN[HBZT]\+",  # EDIFACT service segments: UNH+, UNB+, UNZ+, UNT+
        r"\bBGM\+",  # beginning of message
        r"\b(NAD|LIN|MOA|RFF|DTM|ALC|CUX|PAT|TDT|PAC|PCI|FTX|UNS|CNT)\+",
        r"\b[A-Z]{2,3}\*[0-9A-Z]",  # X12 segment shape: ST*810*, BIG*, ISA*
        r"\bUN/EDIFACT\b",
        r"\bEDIFACT\b",
        r"\bINVOIC:D:\d{2}[AB]:UN\b",
        r"<(?:\w+:)?Invoice\b",  # UBL Invoice root element
        r"\burn:oasis:names:specification:ubl\b",
        r"\bPEPPOL\b",
        r"\bZUGFeRD\b",
        r"\bFactur-X\b",
        r"CrossIndustryInvoice",
    ]
]

EDI_WEAK_KEYWORDS = [
    "edi",
    "invoic",
    "e-invoice",
    "einvoice",
    "ubl",
    "x12",
    "edi segment",
    "interchange",
    "remittance",
    "purchase order message",
]

DOMAINS: dict[str, DomainConfig] = {
    "edi": DomainConfig(
        id="edi",
        display_name="EDI / e-invoicing",
        strong_patterns=EDI_STRONG_PATTERNS,
        weak_keywords=EDI_WEAK_KEYWORDS,
        vector_collection="edi_specs",
        stage1_similarity_threshold=0.55,
        stage2_confidence_threshold=0.5,
        toolset=[
            "parse_edi",
            "validate_with_citation",
            "map_format",
            "generate_synthetic_invoice",
        ],
    )
}


def all_domains() -> list[DomainConfig]:
    return list(DOMAINS.values())
