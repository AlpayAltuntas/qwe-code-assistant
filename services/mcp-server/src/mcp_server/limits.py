"""Shared input hardening for anything that parses untrusted payload content.

No Docker sandbox yet (deferred — see services/mcp-server/README.md), so
these are the actual mitigation for docs/threat-model.md D1/D2 in this
pass: hard size caps before any parsing, and wall-clock timeouts around
parse calls so a pathological payload can't hang the process.
"""

from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutureTimeoutError
from typing import Callable, TypeVar

MAX_INPUT_BYTES = 512_000  # generous for a single invoice; not for a batch
PARSE_TIMEOUT_SECONDS = 5

T = TypeVar("T")

# MCP tool calls run on a worker thread (not the main interpreter thread),
# which rules out signal.alarm-based timeouts (SIGALRM only works in the
# main thread — confirmed the hard way: it raised ValueError at runtime
# under real MCP tool dispatch, even though it worked fine in a plain
# script). Running the guarded call in its own thread and bounding
# .result() works from any calling thread.
_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="edi-parse")


class InputTooLarge(ValueError):
    pass


class ParseTimeout(TimeoutError):
    pass


def check_size(text: str) -> None:
    size = len(text.encode("utf-8"))
    if size > MAX_INPUT_BYTES:
        raise InputTooLarge(f"input is {size} bytes, exceeds the {MAX_INPUT_BYTES}-byte cap")


def run_with_timeout(fn: Callable[[], T], seconds: int = PARSE_TIMEOUT_SECONDS) -> T:
    """Runs fn() with a wall-clock timeout. If it fires, the caller gets
    control back and can report the error — but note this can't forcibly
    kill the worker thread, so a truly runaway parse keeps consuming
    resources in the background until it finishes on its own. Real
    enforcement is what the deferred Docker sandbox is for; this is
    defense-in-depth on top of disabled entity resolution (the actual
    "billion laughs" mitigation) and the size cap above."""
    future = _EXECUTOR.submit(fn)
    try:
        return future.result(timeout=seconds)
    except _FutureTimeoutError as exc:
        raise ParseTimeout(f"parsing exceeded {seconds}s") from exc
