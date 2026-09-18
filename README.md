# Playbook Creator Playbook (PBCPB)

**A meta-playbook for creating domain-specific, executable playbooks.** You load it as context for
a planning session, and an AI agent walks it — 16 phases of scoping, research, architecture, task
engineering, assembly, validation, and structured dry-run — to produce a structured JSON playbook
that another operator (or agent) can then execute.

Provider-agnostic and executable by any AI agent system; **optimized for Claude Code on the Max
plan** (high budget) with a first-class OpenAI Codex profile.

- **The meta-playbook:** [`playbook-creator-playbook.json`](playbook-creator-playbook.json) (v8)
- **Output contract:** [`templates/output-schema.json`](templates/output-schema.json)
- **Start-here skeleton for a new playbook:** [`templates/output-template.json`](templates/output-template.json)
- **Validators:** [`scripts/validate_playbook.py`](scripts/validate_playbook.py) (structural + JSON Schema),
  [`scripts/validate_semantic.py`](scripts/validate_semantic.py) (cross-reference / semantic)

## Why

Building a good playbook by hand is slow and it drifts. PBCPB turns "write a playbook" into a
gated process: it forces you to lock scope before designing, research before architecting, and
validate before shipping — and it produces machine-checkable JSON with roles, gates, cross-cutting
concerns, failure modes, and metrics baked in.

## Quick start

```bash
pip install -r requirements.txt            # just jsonschema

# 1) Read the phases you're about to run
python3 -c "import json;[print(p) for p in json.load(open('playbook-creator-playbook.json'))['phase_summary']]"

# 2) Run it: load playbook-creator-playbook.json as context in your agent and work Phase 0 -> 15.
#    A single agent fills all roles, switching mental context per phase (see usage_instructions).

# 3) Author your output playbook by filling templates/output-template.json (it carries the exact shapes).

# 4) Validate your produced playbook before shipping it:
python3 scripts/validate_playbook.py --no-trace my-playbook.json --schema templates/output-schema.json
python3 scripts/validate_semantic.py my-playbook.json
```

`--no-trace` guarantees the validator runs with no external dependencies. (If you use Langfuse,
omit it and set `PBCPB_TRACE_WORKSPACE`.)

## The 16 phases

0 Commission & Scoping · 1 Domain Research · 2 KB Architecture · 3 KB Bootstrapping ·
4 Process Architecture · 5 Role Engineering (derive a custom team) · 6 Task Engineering ·
7 Output Configuration (compile agents) · 8 Metrics & KPI Definition · 9 JSON Assembly ·
10 JSON Validation · 11 Quality Audit / Gap Analysis · 12 Stress Testing & Structured Dry-Run ·
13 Stakeholder Review · 14 Documentation & Version Control · 15 Continuous Improvement.

Routing: mostly sequential, gate-guarded. If Phase 0 sets `kb_mode != PLAYBOOK_MANAGED`, Phases 2–3
are skipped.

## Custom team engineering (v8)

PBCPB does not force a produced playbook onto a fixed slate of roles. It engineers a team that fits
the domain, end to end:

- **Phase 5 derives the team from the work.** Tasks are clustered along four axes — domain expertise,
  decision authority, tools/access, and independence — and roles fall out of the clusters. The six
  built-in roles are a **palette** (base-on / add / replace / drop), so domain-custom roles like
  `[DSPEngineer]`, `[Deployer]`, or `[SecurityAuditor]` are expected. Each role is written as a
  provider-neutral **agent spec**: `description`, `role_context`, `decision_authority`, `tools`,
  `owns`/`owned_phases`, `interfaces{consumes,produces}`, `agent_assignment`, `defaults{tier,temperature}`.
- **Balanced minimality, with invariants.** Complexity caps are guidance (simple ~3, standard ~5,
  complex ~7), not limits — a specialist beyond the cap is fine when a cluster needs distinct
  expertise/authority/access, justified in one line. Every team must have **one Coordinator**, at
  least one **independent Verifier** (no artifact is verified by its producer — `CCC-11`), and a
  **human/Operator** for irreversible/creative/external decisions.
- **Phase 7 compiles the specs into agents.** Each canonical role spec compiles into concrete agent
  files: Claude Code `.claude/agents/<role>.md` (model resolved from the role's tier via
  `defaults.providers`, tools from the spec), an OpenAI Codex role prompt, and a generic
  `agents/manifest.json`. The spec is the single source of truth; the agent files are rebuildable
  artifacts. These compiled agents are the team that runs the produced playbook.

Team integrity is checked: `validate_semantic.py` fails on a task owner with no matching role
(`CCC-10`) and warns on ownerless tasks, idle roles, and a missing independent verifier. All role-spec
fields are **optional** in the schema, so simpler playbooks (roles as plain strings) stay valid.

## Provider / model configuration

Capability is expressed as abstract **tiers** — `frontier / high / fast` — resolved to concrete
models per provider in `defaults.providers`:

| Provider | frontier | high | fast |
|---|---|---|---|
| `anthropic` (default) | `claude-opus-5` | `claude-sonnet-5` | `claude-haiku-4-5` |
| `openai_codex` | `gpt-5.5` | `gpt-5.5` | `gpt-5.5` |
| `generic` | *your strongest* | *your mid* | *your fast* |

Set `defaults.provider` to switch. `defaults.capability_assessment.phase_minimums` are **floors**
for constrained providers; on **Claude Code Max with high budget the default is to run every phase
at `frontier`** (correctness, not cost, is the binding constraint). Legacy `opus/sonnet/haiku`
names still resolve via `defaults.tier_aliases`.

To run on any other system, map your models into `defaults.providers.generic`.

## Output playbook shape

Every produced playbook conforms to `templates/output-schema.json`: `title, version, description,
workflow_model, roles, scope, cross_cutting_concerns, knowledge_base, checklists, metrics,
usage_instructions, failure_modes, phase_kb_mapping, skill_activation, router, context_preservation`.
Fill `templates/output-template.json` rather than authoring these shapes from memory. A role in
`roles` may be a plain string or an object; the object form carries the optional agent-spec fields
(`role_context`, `decision_authority`, `tools`, `owns`/`owned_phases`, `interfaces`, `agent_assignment`,
`invariant`, `defaults`) that Phase 7 compiles into agent files.

## Validators

- **`validate_playbook.py`** — JSON Schema conformance + structural checks (owner `[Role]` format,
  per-phase context files, context-budget feasibility) + helpful `oneOf` diagnostics. Runs
  standalone; `--no-trace` skips optional tracing. (The context-budget check is skipped with a note
  if the optional compilation engine isn't installed.)
- **`validate_semantic.py`** — cross-reference integrity (failure-mode phase references, handoff
  chains, CCC minimum-phase coverage).

## Tests

```bash
python3 -m pytest -q          # validates the shipped meta-playbook + template against the schema
```

## License

MIT — see [LICENSE](LICENSE).

## Notes

This is a minimal, public distribution focused on the meta-playbook, its output contract, and
validation. Advanced execution tooling (per-phase system-prompt compilation, model-fallback
resolution, KB adapters, checkpointing) is not included here.
