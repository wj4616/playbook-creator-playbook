#!/usr/bin/env python3
"""harvest_session.py — thin front-end orchestrator for the session-harvest updater.

This does NOT extract anything itself (that is the agent's job, driven by
`prompts/playbook-updater.md`). It provides the deterministic scaffolding around that
work so a produced playbook is authored against the real contract and validated to green,
instead of drifting from a remembered schema.

Subcommands:
  harvest-skeleton   Write the section skeleton the front-end prompt fills in.
  scaffold           Copy the schema-valid output template to a working playbook file.
  check              Run both validators (schema + semantic) and report combined status.

All paths default relative to the repo root (this file's grandparent). No third-party
deps beyond what the validators already need (jsonschema).
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "templates" / "output-schema.json"
TEMPLATE = ROOT / "templates" / "output-template.json"

HARVEST_SKELETON = """# Session Harvest — <playbook name>

> Front-end artifact for PBCPB commission_source=session_history. Every item below MUST
> cite the session/segment it came from (CCC-12). Mark single-occurrence patterns
> "verify in future runs". This file is EVIDENCE for Phase 1 ingest, not the playbook.

## 1. Repeated workflows (candidate phases)
- <workflow> — order it actually happened — [session: <id/segment>]

## 2. Failure modes (symptom / root cause / fix / prevention)
- symptom: <...>; root_cause: <...>; fix: <...>; prevention: <...>;
  severity: <crash|error|degraded|cosmetic>; [session: <id>]
  (Reuse an existing FM id from the PBCPB catalog if one matches; else mint FM-NNN.)

## 3. Domain patterns / algorithms (parameters, runtime, cost, gotchas)
- <name>: <usage>; params: <...>; cost: <...>; gotchas: <...>; [session: <id>]
  (If substantial, plan a KB layer in Phase 2 — kb_mode=USER_SUPPLIED — not an inline block.)

## 4. Creative / subjective decision points (candidate human/Operator gates)
- <decision the human stopped to evaluate> — [session: <id>]

## 5. Roles actually played + role confusion observed (input to Phase 5 derivation)
- <role/capability> owned <tasks>; confusion when <...>; [session: <id>]

## 6. Session boundaries + context restated fresh
- boundary at <point>; context reloaded: <...>; [session: <id>]

## 7. Gap analysis (thin coverage, missing validation, questions for the user)
- <gap> — question: <...>
"""


def cmd_harvest_skeleton(args):
    out = Path(args.out)
    if out.exists() and not args.force:
        sys.exit(f"refusing to overwrite {out} (use --force)")
    out.write_text(HARVEST_SKELETON)
    print(f"wrote harvest skeleton -> {out}")
    print("Next: hand it + the raw transcript to prompts/playbook-updater.md to fill.")


def cmd_scaffold(args):
    if not TEMPLATE.exists():
        sys.exit(f"template not found: {TEMPLATE}")
    pb = json.loads(TEMPLATE.read_text())
    pb["title"] = args.name
    out = Path(args.out or f"{args.name}.json")
    if out.exists() and not args.force:
        sys.exit(f"refusing to overwrite {out} (use --force)")
    out.write_text(json.dumps(pb, indent=2, ensure_ascii=False) + "\n")
    print(f"scaffolded schema-valid working playbook -> {out}")
    if args.harvest:
        h = Path(args.harvest)
        if h.exists():
            heads = [ln.strip() for ln in h.read_text().splitlines() if ln.startswith("## ")]
            print(f"harvest sections to fold in from {h}:")
            for x in heads:
                print("   " + x)
        else:
            print(f"(note: --harvest {h} not found)")
    print("Next: fill it from the harvest, then: harvest_session.py check " + str(out))


def _run(script, pb_args):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), *pb_args],
        capture_output=True, text=True,
    )


def cmd_check(args):
    pb = args.playbook
    schema = args.schema or str(SCHEMA)
    struct = _run("validate_playbook.py", ["--no-trace", pb, "--schema", schema])
    sem = _run("validate_semantic.py", [pb])
    print("=== structural + schema ===")
    print((struct.stdout or struct.stderr).rstrip())
    print("=== semantic ===")
    print((sem.stdout or sem.stderr).rstrip())
    ok = struct.returncode == 0 and sem.returncode == 0
    print("\n" + ("PASS — both validators green" if ok else "FAIL — fix the errors above and re-run"))
    sys.exit(0 if ok else 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s1 = sub.add_parser("harvest-skeleton", help="write the harvest section skeleton")
    s1.add_argument("--out", default="session-harvest.md")
    s1.add_argument("--force", action="store_true")
    s1.set_defaults(func=cmd_harvest_skeleton)

    s2 = sub.add_parser("scaffold", help="copy the schema-valid output template")
    s2.add_argument("--name", required=True)
    s2.add_argument("--out")
    s2.add_argument("--harvest")
    s2.add_argument("--force", action="store_true")
    s2.set_defaults(func=cmd_scaffold)

    s3 = sub.add_parser("check", help="run both validators, report combined status")
    s3.add_argument("playbook")
    s3.add_argument("--schema")
    s3.set_defaults(func=cmd_check)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
