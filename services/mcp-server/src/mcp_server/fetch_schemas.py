"""Fetches the public OASIS UBL 2.1 XSD schema chain needed to validate an
Invoice document. Mirrors the maindoc/common directory split from the
official package so the schemas' own relative `schemaLocation` imports
resolve without modification.

Run: uv run mcp-fetch-schemas
"""

import httpx

from mcp_server.config import SCHEMAS_DIR

BASE = "https://docs.oasis-open.org/ubl/os-UBL-2.1/xsd"

MAINDOC = ["UBL-Invoice-2.1.xsd"]
COMMON = [
    "UBL-CommonAggregateComponents-2.1.xsd",
    "UBL-CommonBasicComponents-2.1.xsd",
    "UBL-CommonExtensionComponents-2.1.xsd",
    "UBL-QualifiedDataTypes-2.1.xsd",
    "UBL-UnqualifiedDataTypes-2.1.xsd",
    "CCTS_CCT_SchemaModule-2.1.xsd",
]

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; qwe-code-assistant-mcp-server/0.1)"}


def main() -> None:
    for subdir, files in (("maindoc", MAINDOC), ("common", COMMON)):
        dest_dir = SCHEMAS_DIR / subdir
        dest_dir.mkdir(parents=True, exist_ok=True)
        for filename in files:
            url = f"{BASE}/{subdir}/{filename}"
            response = httpx.get(url, headers=_HEADERS, timeout=30.0, follow_redirects=True)
            response.raise_for_status()
            (dest_dir / filename).write_bytes(response.content)
            print(f"fetched {subdir}/{filename} ({len(response.content)} bytes)")


if __name__ == "__main__":
    main()
