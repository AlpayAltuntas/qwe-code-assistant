"""Append-only JSONL logging for router decisions and ingestion events.

Scoped as sufficient for single-user audit/debug purposes, not a defense
against a privileged local attacker — see docs/threat-model.md R2.
"""

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

from router.config import LOG_EXCERPT_MAX_CHARS, LOGS_DIR

_PII_PATTERNS = [
    re.compile(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}"),  # IBAN-like
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),  # email
    re.compile(r"\b\d{9,15}\b"),  # long numeric IDs (tax/account numbers)
]


def redact(text: str) -> str:
    """Best-effort redaction of common PII shapes before logging an excerpt.

    Defense in depth per docs/threat-model.md I3 — this is not a
    guarantee, just a reduction in what a log leak would expose.
    """
    redacted = text
    for pattern in _PII_PATTERNS:
        redacted = pattern.sub("[redacted]", redacted)
    return redacted


def message_fingerprint(message: str) -> dict[str, Any]:
    """A safe-to-log stand-in for a raw message: hash + short redacted excerpt."""
    digest = hashlib.sha256(message.encode("utf-8")).hexdigest()
    excerpt = redact(message[:LOG_EXCERPT_MAX_CHARS])
    return {
        "sha256": digest,
        "length": len(message),
        "excerpt": excerpt,
    }


def append_jsonl(filename: str, record: dict[str, Any]) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    path: Path = LOGS_DIR / filename
    record = {"ts": time.time(), **record}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def log_router_decision(record: dict[str, Any]) -> None:
    append_jsonl("router.jsonl", record)


def log_ingest_event(record: dict[str, Any]) -> None:
    append_jsonl("ingest.jsonl", record)
