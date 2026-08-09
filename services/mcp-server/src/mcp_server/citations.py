"""Pulls cited spec chunks from the Phase 3 router service for
validate_with_citation. Read-only consumer of the router's own /retrieve
endpoint — this service has no independent copy of the RAG corpus and no
authority to assert anything the router didn't actually retrieve (see
docs/threat-model.md E3).

If the router isn't running, citations are simply omitted — a validation
verdict is still deterministic and complete without them, just uncited.
"""

import httpx

from mcp_server.config import ROUTER_BASE_URL, ROUTER_TOKEN_PATH


def _token() -> str | None:
    if not ROUTER_TOKEN_PATH.exists():
        return None
    return ROUTER_TOKEN_PATH.read_text().strip()


def fetch_citations(message: str, domain: str = "edi", k: int = 3) -> list[dict]:
    token = _token()
    if not token:
        return []
    try:
        response = httpx.post(
            f"{ROUTER_BASE_URL}/retrieve",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": message, "domain": domain, "k": k},
            timeout=10.0,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError:
        return []
