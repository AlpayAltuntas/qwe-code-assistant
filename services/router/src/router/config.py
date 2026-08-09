"""Central configuration for the router service.

All values are local-machine defaults; nothing here points off-box.
"""

from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = SERVICE_ROOT / "data"
STAGING_DIR = DATA_DIR / "staging"
CORPUS_DIR = DATA_DIR / "corpus"
CHROMA_DIR = DATA_DIR / "chroma"
LOGS_DIR = DATA_DIR / "logs"
MANIFEST_PATH = DATA_DIR / "manifest.json"
TOKEN_PATH = SERVICE_ROOT / ".router-token"

OLLAMA_BASE_URL = "http://127.0.0.1:11434"
CHAT_MODEL = "qwen3-coder:30b"
EMBED_MODEL = "nomic-embed-text"

# Loopback only — see docs/threat-model.md S1/I2.
HOST = "127.0.0.1"
PORT = 8787

# Message content logged for correlation is truncated to this length and
# never the raw payload beyond it — see docs/threat-model.md I3.
LOG_EXCERPT_MAX_CHARS = 120
