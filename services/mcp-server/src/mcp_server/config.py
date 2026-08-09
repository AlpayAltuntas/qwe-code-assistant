from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS_DIR = SERVICE_ROOT / "schemas"
UBL_INVOICE_XSD = SCHEMAS_DIR / "maindoc" / "UBL-Invoice-2.1.xsd"

# Sibling service from Phase 3 — reused for citations, never for tool
# execution itself (see docs/threat-model.md E3: this service must not
# become a second, unvetted path to "validated" verdicts).
ROUTER_BASE_URL = "http://127.0.0.1:8787"
ROUTER_TOKEN_PATH = SERVICE_ROOT.parent / "router" / ".router-token"
