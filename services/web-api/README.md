# Web API (Phase 6 placeholder)

Fastify (TypeScript) backend for `apps/web`. Responsibilities:

- Serves the SPA and its REST/RPC API
- Calls the existing Python router + MCP server for all EDI logic (parse/validate/map/generate, RAG retrieval) — same loopback + token-auth contract Continue uses, no parallel implementation of tool logic (see threat-model.md E3)
- Owns the only direct connection to PostgreSQL (Drizzle ORM), storing metadata/audit records only — citation manifests, validation verdicts, router-decision logs, job records. Never raw invoice content by default.
- Bound to `127.0.0.1` only; strict CORS allowlist; no wildcard origins (see threat-model.md S3)

Postgres runs locally via Docker, loopback/Docker-internal only, never a published port.

Not implemented yet — sequenced after Phases 3–5. See `docs/architecture.md`.
