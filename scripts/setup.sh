#!/usr/bin/env bash
set -euo pipefail

echo "==> Checking Homebrew"
command -v brew >/dev/null || { echo "Homebrew is required: https://brew.sh"; exit 1; }

echo "==> Ensuring Ollama is installed"
brew list ollama >/dev/null 2>&1 || brew install ollama

echo "==> Ensuring VS Code is installed"
# Check if VS Code is installed, and install it if not
command -v code >/dev/null || brew install visual-studio-code
brew list --cask visual-studio-code >/dev/null 2>&1 || brew install --cask visual-studio-code

echo "==> Starting Ollama"
brew services start ollama >/dev/null

echo "==> Waiting for Ollama to respond on 127.0.0.1:11434"
for _ in $(seq 1 30); do
  curl -s 127.0.0.1:11434 >/dev/null 2>&1 && break
  sleep 1
done

echo "==> Pulling qwen3-coder:30b (this is a large download)"
ollama pull qwen3-coder:30b

echo "==> Pulling nomic-embed-text (for the RAG grounding layer)"
ollama pull nomic-embed-text

echo "==> Installing Continue.dev VS Code extension"
code --install-extension continue.continue

echo "==> Checking uv (for the Python router service)"
command -v uv >/dev/null || brew install uv

ROUTER_DIR="$(dirname "$0")/../services/router"

echo "==> Syncing router service dependencies"
(cd "$ROUTER_DIR" && uv sync)

echo "==> Generating router auth token (if not already present)"
ROUTER_TOKEN=$(cd "$ROUTER_DIR" && uv run python -c "from router.auth import ensure_token; print(ensure_token())")

echo "==> Installing Continue.dev config"
mkdir -p "$HOME/.continue"
sed "s/__ROUTER_TOKEN__/$ROUTER_TOKEN/" "$(dirname "$0")/../apps/vscode-config/config.yaml" > "$HOME/.continue/config.yaml"

echo "==> Done. Open this folder (or any project) in VS Code and open the Continue panel."
echo ""
echo "To use the EDI/e-invoicing specialist layer (Phase 3), the router service"
echo "must be running: in a separate terminal, run"
echo "  cd services/router && uv run router-ingest fetch && uv run router-ingest promote --all && uv run router-ingest index"
echo "once to build the spec corpus, then"
echo "  cd services/router && uv run router-serve"
echo "to start the router API before opening Continue. If you re-run this script after the"
echo "router has already generated a token, re-run it again afterward so config.yaml picks up"
echo "the same token value (or just replace __ROUTER_TOKEN__/the old token in ~/.continue/config.yaml by hand)."
