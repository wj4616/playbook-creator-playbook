# Playbook Creator Playbook (PBCPB)

**A meta-playbook for creating domain-specific, executable playbooks.** You load it as context for
a planning session, and an AI agent walks it — 16 phases of scoping, research, architecture, task
engineering, assembly, validation, and structured dry-run — to produce a structured JSON playbook
that another operator (or agent) can then execute.

Provider-agnostic and executable by any AI agent system; **optimized for Claude Code on the Max
plan** (high budget) with a first-class OpenAI Codex profile.

- **The meta-playbook:** [`playbook-creator-playbook.json`](playbook-creator-playbook.json) (v7)
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
4 Process Architecture · 5 Role Engineering · 6 Task Engineering · 7 Output Configuration ·
8 Metrics & KPI Definition · 9 JSON Assembly · 10 JSON Validation · 11 Quality Audit / Gap
Analysis · 12 Stress Testing & Structured Dry-Run · 13 Stakeholder Review · 14 Documentation &
Version Control · 15 Continuous Improvement.

Routing: mostly sequential, gate-guarded. If Phase 0 sets `kb_mode != PLAYBOOK_MANAGED`, Phases 2–3
are skipped.

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
Fill `templates/output-template.json` rather than authoring these shapes from memory.

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
