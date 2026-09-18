# Changelog

All notable changes to the Playbook Creator Playbook. This public distribution starts at v7.

## v7 — 2026-09-18
- **Provider-agnostic capability model.** Abstract tiers `frontier / high / fast` (legacy
  `opus/sonnet/haiku` kept as `tier_aliases`), resolved to current models per provider in
  `defaults.providers` (anthropic: `claude-opus-5/sonnet-5/haiku-4-5`; `openai_codex`: `gpt-5.5`;
  `generic`: placeholders). `defaults.provider` selects the active agent system.
- **Optimized for Claude Code Max (high budget):** `claude_code_max_profile` = run all phases at
  `frontier`; `phase_minimums` are floors for constrained/other providers. Working context budget
  raised to 120k; per-provider window sizes recorded. Codex profile documented.
- Roles use the tier vocabulary; `output-template.json` defaults modernized to match.

## v6 — 2026-09-18
- **Validators run in any environment:** Langfuse/tracing made optional (no-op shims), trace id
  sanitized to valid hex, `--no-trace` bypass, null-safe client calls.
- **Assembly no longer drifts from the schema:** Phase 9 loads `output-schema.json` +
  `output-template.json` and self-validates before Phase 10; better `oneOf` error diagnostics.
- Phase 6 encodes task-authoring rules (`[Role]` owners; tracking files in every `context_load`).
- Phase 12 gains an optional **execution-grounded pilot** gate (prove it runs, not just parses).
- Documented single-agent vs role-agent execution modes; surfaced the `kb_mode`
  portability-vs-reproducibility tradeoff at Phase 0. Fixed a stale failure-mode phase reference.

## v5 and earlier
- Internal iterations (16-phase structure, compilation tooling, KB adapters). Not part of this
  public distribution.
