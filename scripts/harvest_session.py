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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import session_store as store  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SELF = Path(__file__).resolve()
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


# ----------------------------------------------------------------- sessions (catalog)
def _catalog(args):
    return Path(args.catalog) if getattr(args, "catalog", None) else store.DEFAULT_CATALOG


def cmd_sessions(args):
    if args.sessions_cmd == "index":
        store.index(_catalog(args), quiet=args.quiet)
    elif args.sessions_cmd == "list":
        rows = store.list_sessions(
            _catalog(args), project=args.project, since=args.since, until=args.until,
            tag=args.tag, source=args.source, query=args.query)
        rows = rows[: args.limit] if args.limit else rows
        if not rows:
            print("no sessions match (run: harvest_session.py sessions index)")
            return
        for r in rows:
            tools = sum(r.get("tools", {}).values())
            tg = (" [" + ",".join(r["tags"]) + "]") if r.get("tags") else ""
            label = (r.get("title") or r.get("first_prompt") or "").replace("\n", " ").replace("\r", " ").strip()
            print(f"{(r.get('start') or '')[:10]}  {r['source'][:2]}  {r['id']}  "
                  f"{r.get('user_turns',0)}u/{tools}t  {label[:60]}{tg}")
            if args.paths:
                print(f"        {r['path']}")
    elif args.sessions_cmd == "tag":
        try:
            tags = store.tag(_catalog(args), args.id, args.tags, remove=args.remove)
            print(f"{args.id} tags: {tags or '—'}")
        except KeyError:
            sys.exit(f"session not in catalog: {args.id} (run: sessions index)")


def cmd_ingest(args):
    cat = _catalog(args)
    if args.ids:
        ids = args.ids
    else:
        rows = store.list_sessions(cat, project=args.project, since=args.since, until=args.until,
                                   tag=args.tag, source=args.source, query=args.query)
        rows = rows[: args.limit] if args.limit else rows
        ids = [r["id"] for r in reversed(rows)]  # chronological for the digest
    if not ids:
        sys.exit("no sessions selected (try: harvest_session.py sessions list ...)")
    result = store.ingest(ids, cat, fmt=args.format, max_output=args.max_output,
                          include_thinking=args.include_thinking)
    text = result if isinstance(result, str) else json.dumps(result, indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(text + ("\n" if not text.endswith("\n") else ""))
        print(f"ingested {len(ids)} session(s) -> {args.out}")
        print("Next: distill it into research/session-harvest.md via prompts/playbook-updater.md")
    else:
        print(text)


# ----------------------------------------------------------------- hooks
def _hook_command():
    return f"python3 {SELF} sessions index --quiet"


def cmd_hooks(args):
    snippet = {"SessionEnd": [{"hooks": [{"type": "command", "command": _hook_command()}]}]}
    settings = Path(args.settings) if args.settings else (Path.home() / ".claude" / "settings.json")
    if args.hooks_cmd == "print":
        print("Add to " + str(settings) + " under \"hooks\":\n")
        print(json.dumps(snippet, indent=2))
        return
    data = {}
    if settings.exists():
        try:
            data = json.loads(settings.read_text())
        except json.JSONDecodeError:
            sys.exit(f"{settings} is not valid JSON — fix it or edit by hand")
    hooks = data.setdefault("hooks", {})
    se = hooks.setdefault("SessionEnd", [])
    present = any("harvest_session.py sessions index" in h.get("command", "")
                  for grp in se for h in grp.get("hooks", []))
    if args.hooks_cmd == "install":
        if present:
            print("SessionEnd reindex hook already installed.")
            return
        if settings.exists():
            bak = settings.with_suffix(".json.bak")
            bak.write_text(settings.read_text())
            print(f"backed up {settings} -> {bak}")
        se.append(snippet["SessionEnd"][0])
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps(data, indent=2) + "\n")
        print(f"installed SessionEnd reindex hook into {settings}")
        print("Every finished session now refreshes the catalog automatically.")
    elif args.hooks_cmd == "uninstall":
        for grp in se:
            grp["hooks"] = [h for h in grp.get("hooks", []) if "harvest_session.py sessions index" not in h.get("command", "")]
        hooks["SessionEnd"] = [g for g in se if g.get("hooks")]
        settings.write_text(json.dumps(data, indent=2) + "\n")
        print(f"removed the reindex hook from {settings}")


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

    # sessions
    ss = sub.add_parser("sessions", help="catalog the transcripts your agents already record")
    ssub = ss.add_subparsers(dest="sessions_cmd", required=True)
    si = ssub.add_parser("index", help="(re)scan all Claude Code + Codex sessions into the catalog")
    si.add_argument("--catalog"); si.add_argument("--quiet", action="store_true")
    sl = ssub.add_parser("list", help="list/filter catalogued sessions")
    for a in ("--project", "--since", "--until", "--tag", "--source", "--query", "--catalog"):
        sl.add_argument(a)
    sl.add_argument("--limit", type=int); sl.add_argument("--paths", action="store_true")
    st = ssub.add_parser("tag", help="add/remove tags on a session")
    st.add_argument("id"); st.add_argument("tags", nargs="+")
    st.add_argument("--remove", action="store_true"); st.add_argument("--catalog")
    ss.set_defaults(func=cmd_sessions)

    # ingest
    ig = sub.add_parser("ingest", help="normalize selected sessions into a digest for the prompt")
    ig.add_argument("ids", nargs="*")
    for a in ("--project", "--since", "--until", "--tag", "--source", "--query", "--catalog", "--out"):
        ig.add_argument(a)
    ig.add_argument("--limit", type=int)
    ig.add_argument("--format", choices=["md", "json"], default="md")
    ig.add_argument("--max-output", dest="max_output", type=int, default=500)
    ig.add_argument("--include-thinking", dest="include_thinking", action="store_true")
    ig.set_defaults(func=cmd_ingest)

    # hooks
    hk = sub.add_parser("hooks", help="install the SessionEnd auto-reindex hook")
    hsub = hk.add_subparsers(dest="hooks_cmd", required=True)
    for name, helptext in (("print", "print the settings snippet"),
                           ("install", "merge the hook into ~/.claude/settings.json (backs up first)"),
                           ("uninstall", "remove the hook")):
        hp = hsub.add_parser(name, help=helptext)
        hp.add_argument("--settings")
    hk.set_defaults(func=cmd_hooks)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
