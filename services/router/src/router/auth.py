"""Per-session shared-secret token for the router API.

Mitigates docs/threat-model.md S2: a rogue local process/extension
spoofing a trusted client. "localhost" is not treated as inherently
trusted — every request must present this token.
"""

import os
import secrets

from router.config import TOKEN_PATH


def ensure_token() -> str:
    """Return the current token, generating one on first run.

    The token file is written with 0600 permissions (owner read/write
    only) so other local users on the machine cannot read it.
    """
    if TOKEN_PATH.exists():
        return TOKEN_PATH.read_text().strip()

    token = secrets.token_urlsafe(32)
    TOKEN_PATH.write_text(token)
    os.chmod(TOKEN_PATH, 0o600)
    return token


def verify_token(candidate: str | None, expected: str) -> bool:
    if candidate is None:
        return False
    return secrets.compare_digest(candidate, expected)
