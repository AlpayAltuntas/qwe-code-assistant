# Web API (Phase 6)

Fastify (TypeScript) backend for `apps/web`. The only component with direct Postgres access; owns request validation (zod) and audit logging. All EDI logic lives in `services/mcp-server` — this is a thin client of it, not a parallel implementation (docs/threat-model.md E3).

## Setup

```sh
npm install
cp .env.example .env   # fill in DATABASE_URL, MCP_SERVER_DIR (absolute path)
npm run db:generate    # regenerate drizzle/ SQL from src/db/schema.ts, if schema changed
npm run db:migrate     # apply migrations (needs a role with CREATE TABLE — see below)
npm run dev            # http://127.0.0.1:8788
```

### Database

Runs on an existing local Postgres.app instance rather than a fresh Docker container — see `docs/architecture.md`'s Phase 6 build note. One-time setup, as a superuser (e.g. your own `psql` login):

```sql
CREATE DATABASE qwe_web_ui;
CREATE ROLE qwe_web_api WITH LOGIN PASSWORD '...';
GRANT CONNECT ON DATABASE qwe_web_ui TO qwe_web_api;
GRANT USAGE ON SCHEMA public TO qwe_web_api;
-- after running migrations as the superuser:
GRANT INSERT, SELECT ON tool_invocations TO qwe_web_api;             -- audit trail: no UPDATE/DELETE (R3)
GRANT USAGE, SELECT ON SEQUENCE tool_invocations_id_seq TO qwe_web_api;
GRANT SELECT, INSERT, UPDATE, DELETE ON mapping_profiles TO qwe_web_api;  -- user config: full CRUD
GRANT USAGE, SELECT ON SEQUENCE mapping_profiles_id_seq TO qwe_web_api;
```

`qwe_web_api` (the app's runtime role, in `DATABASE_URL`) deliberately cannot create/alter tables — migrations run as a superuser, the app only ever reads/writes rows.

## Endpoints

- `POST /api/generate` — `{format, numLines, seed?}` → calls `generate_synthetic_invoice`
- `POST /api/parse` — `{content, format}` → calls `parse_edi`
- `POST /api/validate` — `{content, format}` → calls `validate_with_citation`
- `POST /api/mapping-fields/source` — `{content, format}` (`format` any of `edifact`/`ubl`/`cii`/`zugferd`) → calls `describe_mapping_source_fields`, returns `{header, lineTemplate, lineCount}` where each field is `{parent_tag, tag, occurrence, label, value}` — one address shape regardless of source format, addressed by tag+occurrence rather than raw position, for the Mapping tab's dropdowns (see `services/mcp-server/src/mcp_server/ir.py`)
- `GET /api/mapping-fields/target` — static list of ~30 header + ~10 line canonical target fields, grouped (`{field, label, group}`) for the UI; shared by both the Mapping tab and the Create tab, and by every target format (not format-specific — a given field's `notes` at apply/build time say whether it landed)
- `GET /api/mapping-profiles`, `POST /api/mapping-profiles`, `GET/PUT/DELETE /api/mapping-profiles/:id` — saved mapping CRUD, any of EDIFACT/UBL/CII/ZUGFeRD as `fromFormat`/`toFormat`
- `POST /api/mapping-profiles/:id/apply` — `{content}` → calls `apply_mapping_profile` with the saved profile's field mappings
- `POST /api/documents` — `{header, lines, toFormat}` → calls `build_document`; builds a target document directly from field values the user typed in (Create tab), with no source document or field mapping involved — `header` and `lines[]` are keyed by the same canonical field/subfield names as the mapping target catalog

Every call to `generate`/`parse`/`validate`/mapping-apply/`documents` writes one row to `tool_invocations` (tool, format, short summary) — metadata only, never the submitted content (docs/threat-model.md I1).

## How it reaches the EDI tools

Spawns `services/mcp-server` as a stdio subprocess per call, via `@modelcontextprotocol/sdk`'s `StdioClientTransport` — exactly what Continue's `mcpServers:` does. No long-lived connection, no caching: simpler to reason about for a single-user local tool with light request volume, at the cost of one Python interpreter startup per call (~600ms measured). See `src/mcp/client.ts`.

## Security

- Bound to `127.0.0.1` only.
- CORS: strict allowlist (`CORS_ORIGIN`, no wildcard) — verified at build time that a disallowed `Origin` gets no `Access-Control-Allow-Origin` header on either the preflight or the actual response, which is what stops a "localhost drive-by" from another browser tab (docs/threat-model.md S3).
