# Changelog

All notable changes to the Playbook Creator Playbook. This public distribution starts at v7.

## v10 — 2026-09-18
- **Session capture, management, and normalization — from the transcripts your agents already record.**
  Claude Code writes a complete JSONL per session (`~/.claude/projects/<slug>/<id>.jsonl`) and Codex
  under `~/.codex/sessions/`, so capture is already solved. v10 adds the select + normalize layer:
  - **New `scripts/session_store.py` + `harvest_session.py` subcommands.** `sessions index` builds a
    rebuildable catalog (id, project, time range, tool counts, git branch, the Claude-generated title,
    and **user tags**, stored at `~/.claude/pbcpb/session-catalog.json`); `sessions list/tag` find and
    **group a multi-session build into one campaign**; `ingest [--tag <campaign>]` normalizes one or
    many sessions into a **lossless-structured digest** (turn-ordered asks, tool calls with args,
    results, file edits, git branch) — the harvest input, no manual paste. Only tags are user data;
    the JSONL stays ground truth.
  - **`hooks print | install | uninstall`** — merges a `SessionEnd` hook into `~/.claude/settings.json`
    that auto-refreshes the catalog (backs up first, idempotent, preserves existing keys/hooks).
  - The updater prompt now sources its material from `ingest`; Phase 0 `commission_source` points at
    the session tooling. Meta-playbook → v10.
  - Sessions are never auto-summarized into prose (that would destroy error text / tool sequences /
    file diffs); catalog and digest are derived, regenerable views.
- **Validator hardening** (surfaced by dogfooding the harvest flow): `validate_semantic.py` now
  resolves real-world `role_mindset` labels — `Role (annotation)`, `Role + Role` composites (each
  validated; both satisfy CCC-10), and a defined role as a whole-word leading prefix
  (`Security Auditor` → `Security`) — and adds a close-match suggestion on genuine misses. The CCC-11
  independent-verifier heuristic now also recognizes `security` / `pentest` / `penetration` /
  `adversar` / `red team` / `assur` / `inspect` role language.

## v9 — 2026-09-18
- **The session-harvest updater is now a front-end to the pipeline, not a parallel generator.**
  Previously the prompt carried a prose copy of the contract and one-shot-emitted a playbook (so it
  drifted from the schema and skipped every gate). v9 makes it *use* PBCPB:
  - **Author against the real contract.** The prompt loads `templates/output-schema.json` as ground
    truth, fills `templates/output-template.json`, reuses the failure-mode / cross-cutting-concern
    catalogs, and **validates to green** with the real validators. Non-contract sections dropped.
    New **FM-037** (contract-fidelity drift).
  - **Route the harvest through the meta-playbook.** Phase 0 records `commission_source`
    (`fresh` | `session_history` | `existing_playbook_revision`); Phase 1 gains a conditional
    *ingest + validate the session harvest* task that treats it as **cited evidence** (verify
    citations, flag single-occurrence patterns, reuse the FM catalog) then hands off to Phases 4–15
    (role derivation, assembly, validation, Phase 11 gap analysis, Phase 12 stress-test + dry-run).
    New **CCC-12** (evidence traceability), **FM-038/039**. The router documents the branch.
  - **Runtime wiring.** Harvested roles compile via Phase 7 agent compilation; domain patterns route
    to a KB layer (`kb_mode=USER_SUPPLIED`) instead of inline blocks; capability tiers emitted.
- **New `scripts/harvest_session.py`** (stdlib + jsonschema): `harvest-skeleton` writes the cited-
  evidence skeleton, `scaffold` copies the schema-valid template, `check` runs both validators and
  reports combined green/red — the validate-to-green loop the prompt and Phase 10 depend on.
- The prompt now has explicit **integrated** (recommended) and **standalone** modes.

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
