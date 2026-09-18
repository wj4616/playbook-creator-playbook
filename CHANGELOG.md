# Changelog

All notable changes to the Playbook Creator Playbook. This public distribution starts at v7.

## v8 — 2026-09-18
- **Domain-custom role & agent generation.** Produced playbooks are no longer forced onto a fixed
  six-role slate. **Phase 5** now *derives* a bespoke execution team from the actual work — clustering
  tasks along four axes (domain expertise, decision authority, tools/access, independence). The
  six-role library becomes a **palette** (base-on / add / replace / drop); domain-custom `[RoleName]`s
  are expected. Each role is written as a provider-neutral **agent spec** (`role_context`,
  `decision_authority`, `tools`, `owns`/`owned_phases`, `interfaces{consumes,produces}`,
  `agent_assignment`, `defaults{tier,temperature}`).
- **Balanced minimality gate + mandatory invariants:** complexity caps are guidance (simple ~3,
  standard ~5, complex ~7), not limits — specialists allowed with a one-line justification. Every
  team must have exactly one **Coordinator**, at least one **independent Verifier** (no artifact
  verified by its producer), and a **human/Operator** for irreversible/creative/external decisions.
- **Phase 7 agent compilation:** canonical role specs compile into per-provider agent files
  (Claude Code `.claude/agents/*.md` with tier→model resolution, Codex prompts, generic
  `agents/manifest.json`). The spec is the source of truth; agent files are rebuildable artifacts.
- **+CCC-10** (team completeness/ownership) and **+CCC-11** (independent verification);
  **+FM-032…036**. Schema documents optional role-spec fields (`decision_authority`, `tools`, `owns`,
  `owned_phases`, `interfaces`, `invariant`) — all optional, existing playbooks stay valid.
- `validate_semantic.py` gains team-completeness checks: undefined task owner → error; ownerless
  task, defined-but-idle role, and absent independent verifier → warnings.
- **Bundled generator prompt:** `prompts/playbook-updater.md` — turns a raw AI-development session
  history into a schema-shaped playbook + gap analysis; updated to the v8 contract (custom-team
  derivation, invariants, optional role-spec fields, CCC-10/11, four-value severity enum).

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
