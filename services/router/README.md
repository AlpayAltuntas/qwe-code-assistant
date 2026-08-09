# Router service (Phase 3 placeholder)

Will house the hybrid-cascade domain router described in `docs/architecture.md`:

- Stage 0: keyword/lexicon pre-filter (near-zero cost, always runs)
- Stage 1: embedding similarity against the domain's vector store collection
- Stage 2: rare schema-constrained LLM classification fallback

Not implemented yet — Tier 1 (the generalist) does not depend on this service.
