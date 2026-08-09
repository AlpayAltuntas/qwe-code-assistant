# qwe-code-assistant

A local, private, offline coding assistant — a generalist pair-programmer for any language, with a separable EDI/e-invoicing specialist layer that engages only when relevant. Everything runs on-device via [Ollama](https://ollama.com); no code, invoice data, or PII leaves the machine.

See [`docs/architecture.md`](docs/architecture.md) for the component design and [`docs/threat-model.md`](docs/threat-model.md) for the STRIDE / OWASP-LLM-Top-10 analysis.

## Status

**Phase 1 (current):** minimal generalist assistant. Chat, inline edit, autocomplete, and repo-context queries via Continue.dev, backed by Qwen3-Coder-30B-A3B running locally through Ollama. No EDI/RAG layer yet — that's Phase 3+.

## Prerequisites

- macOS, Apple Silicon, 32GB+ unified memory
- [Homebrew](https://brew.sh)
- Ollama and VS Code (installed via the setup script below)

## Setup

```sh
./scripts/setup.sh
```

This installs Ollama + VS Code (if missing), starts the Ollama service, pulls `qwen3-coder:30b`, and installs the Continue.dev extension.

Then, copy `apps/vscode-config/config.yaml` to `~/.continue/config.yaml` (the setup script does this too) so Continue points at the local model.

## Verifying it works

```sh
curl 127.0.0.1:11434/v1/models
```

should list `qwen3-coder:30b`. Then open this folder (or any project) in VS Code, open the Continue panel, and:

1. Ask it to explain a file.
2. Request a small inline edit/refactor.
3. Ask it to generate a unit test for a function.

All three should stream responses from the local model with no network activity — confirm via Activity Monitor's Network tab or `nettop` while chatting.

## Roadmap

1. **Phase 1** — this repo's current state: generalist assistant, any language.
2. **Phase 2** — harden the generalist: repo-scale workflows, review/test-gen commands, dev-up script.
3. **Phase 3** — RAG grounding layer for EDI/e-invoicing specs, with an observable, overridable auto-router (`services/router/`).
4. **Phase 4** — EDI tool functions: parse/explain, validate-with-citation, format mapping (`services/mcp-server/`).
5. **Phase 5** — synthetic test-invoice generator across formats, including ZUGFeRD.

## License

Apache-2.0 — see [`LICENSE`](LICENSE).
