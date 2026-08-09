"""Shared input hardening for anything that parses untrusted payload content.

No Docker sandbox yet (deferred — see services/mcp-server/README.md), so
these are the actual mitigation for docs/threat-model.md D1/D2 in this
pass: hard size caps before any parsing, and wall-clock timeouts around
parse calls so a pathological payload can't hang the process.
"""

import signal
from contextlib import contextmanager

MAX_INPUT_BYTES = 512_000  # generous for a single invoice; not for a batch
PARSE_TIMEOUT_SECONDS = 5


class InputTooLarge(ValueError):
    pass


class ParseTimeout(TimeoutError):
    pass


def check_size(text: str) -> None:
    size = len(text.encode("utf-8"))
    if size > MAX_INPUT_BYTES:
        raise InputTooLarge(f"input is {size} bytes, exceeds the {MAX_INPUT_BYTES}-byte cap")


@contextmanager
def parse_timeout(seconds: int = PARSE_TIMEOUT_SECONDS):
    """Unix-only wall-clock timeout (SIGALRM) around a parse call.

    Good enough for a single-user local service handling one request at a
    time; not a substitute for the process-level isolation a real sandbox
    (Docker, deferred) would provide against a truly adversarial payload.
    """

    def _on_alarm(signum, frame):
        raise ParseTimeout(f"parsing exceeded {seconds}s")

    previous = signal.signal(signal.SIGALRM, _on_alarm)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
