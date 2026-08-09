#!/usr/bin/env bash
set -euo pipefail

echo "==> Checking Homebrew"
command -v brew >/dev/null || { echo "Homebrew is required: https://brew.sh"; exit 1; }

echo "==> Ensuring Ollama is installed"
brew list ollama >/dev/null 2>&1 || brew install ollama

echo "==> Ensuring VS Code is installed"
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

echo "==> Installing Continue.dev VS Code extension"
code --install-extension continue.continue

echo "==> Installing Continue.dev config"
mkdir -p "$HOME/.continue"
cp "$(dirname "$0")/../apps/vscode-config/config.yaml" "$HOME/.continue/config.yaml"

echo "==> Done. Open this folder (or any project) in VS Code and open the Continue panel."
