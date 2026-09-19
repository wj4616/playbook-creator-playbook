#!/usr/bin/env python3
"""session_store.py — catalog + normalize the sessions your agents ALREADY record.

Capture is not built here: Claude Code writes a complete JSONL transcript per session under
~/.claude/projects/<slug>/<id>.jsonl, and Codex under ~/.codex/sessions/**/*.jsonl. This module
INDEXES those (a rebuildable catalog with user-assignable tags) and NORMALIZES one or many of them
into a lossless-structured digest that the playbook-updater prompt distills into a session harvest.

Ground truth stays the JSONL. The catalog is a derived view; only `tags` are user data and are
preserved across re-index.

Used via `harvest_session.py sessions ...` / `harvest_session.py ingest ...`, or standalone.
"""
from __future__ import annotations
import json
import os
from datetime import datetime
from pathlib import Path

CC_ROOT = Path.home() / ".claude" / "projects"
CODEX_ROOT = Path.home() / ".codex" / "sessions"
DEFAULT_CATALOG = Path(
    os.environ.get("PBCPB_SESSION_CATALOG", str(Path.home() / ".claude" / "pbcpb" / "session-catalog.json"))
)


# ----------------------------------------------------------------- discovery + scan
def discover():
    """Yield (source, path) for every session transcript on disk."""
    for p in sorted(CC_ROOT.glob("*/*.jsonl")):
        yield "claude-code", p
    if CODEX_ROOT.exists():
        for p in sorted(CODEX_ROOT.glob("**/*.jsonl")):
            yield "codex", p


def _iter_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


def scan_cc(path: Path) -> dict:
    rec = {"id": path.stem, "source": "claude-code", "project": path.parent.name,
           "path": str(path), "title": None, "first_prompt": None,
           "start": None, "end": None, "messages": 0, "user_turns": 0,
           "assistant_turns": 0, "tools": {}, "git_branch": None}
    for o in _iter_json(path):
        t = o.get("type")
        ts = o.get("timestamp")
        if ts:
            rec["start"] = rec["start"] or ts
            rec["end"] = ts
        if o.get("gitBranch"):
            rec["git_branch"] = o["gitBranch"]
        if t == "ai-title" and o.get("aiTitle"):
            rec["title"] = o["aiTitle"]
        if t in ("user", "assistant"):
            rec["messages"] += 1
            msg = o.get("message", {}) or {}
            c = msg.get("content")
            if t == "user" and isinstance(c, str):
                rec["user_turns"] += 1
                if rec["first_prompt"] is None:
                    rec["first_prompt"] = c[:200]
            elif t == "assistant":
                rec["assistant_turns"] += 1
                for b in (c if isinstance(c, list) else []):
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        n = b.get("name", "?")
                        rec["tools"][n] = rec["tools"].get(n, 0) + 1
    rec["mtime"] = path.stat().st_mtime if path.exists() else 0
    return rec


def scan_codex(path: Path) -> dict:
    rec = {"id": path.stem, "source": "codex", "project": None, "path": str(path),
           "title": None, "first_prompt": None, "start": None, "end": None,
           "messages": 0, "user_turns": 0, "assistant_turns": 0, "tools": {}, "git_branch": None}
    for o in _iter_json(path):
        ts = o.get("timestamp")
        if ts:
            rec["start"] = rec["start"] or ts
            rec["end"] = ts
        t = o.get("type")
        pl = o.get("payload", {}) or {}
        if t == "session_meta":
            rec["id"] = pl.get("id", rec["id"])
            rec["project"] = pl.get("cwd")
        elif t == "event_msg":
            pt = pl.get("type", "")
            if "user" in pt:
                rec["user_turns"] += 1
                txt = pl.get("message") or pl.get("text")
                if isinstance(txt, str) and rec["first_prompt"] is None:
                    rec["first_prompt"] = txt[:200]
            elif "agent" in pt or "assistant" in pt:
                rec["assistant_turns"] += 1
            rec["messages"] += 1
    if rec["project"]:
        rec["project"] = "codex:" + Path(rec["project"]).name
    rec["mtime"] = path.stat().st_mtime if path.exists() else 0
    return rec


# ----------------------------------------------------------------- catalog persistence
def load_catalog(catalog_path: Path = DEFAULT_CATALOG) -> dict:
    if catalog_path.exists():
        try:
            return json.loads(catalog_path.read_text())
        except (OSError, json.JSONDecodeError):
            pass
    return {"sessions": {}}


def save_catalog(cat: dict, catalog_path: Path = DEFAULT_CATALOG):
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(json.dumps(cat, indent=2, ensure_ascii=False) + "\n")


def index(catalog_path: Path = DEFAULT_CATALOG, quiet: bool = False) -> dict:
    """(Re)scan every transcript; preserve user tags; write the catalog."""
    cat = load_catalog(catalog_path)
    old = cat.get("sessions", {})
    sessions = {}
    n_new = 0
    for source, path in discover():
        try:
            rec = scan_cc(path) if source == "claude-code" else scan_codex(path)
        except Exception:
            continue
        prev = old.get(rec["id"])
        rec["tags"] = prev.get("tags", []) if prev else []   # tags are the only user data — keep them
        if not prev:
            n_new += 1
        sessions[rec["id"]] = rec
    cat = {"sessions": sessions, "indexed_at": datetime.now().isoformat(timespec="seconds")}
    save_catalog(cat, catalog_path)
    if not quiet:
        print(f"indexed {len(sessions)} sessions ({n_new} new) -> {catalog_path}")
    return cat


def _match(rec, project, since, until, tag, source, query):
    if project and project.lower() not in (rec.get("project") or "").lower():
        return False
    if source and rec.get("source") != source:
        return False
    if tag and tag not in rec.get("tags", []):
        return False
    if since and (rec.get("start") or "") < since:
        return False
    if until and (rec.get("start") or "") > until:
        return False
    if query:
        hay = " ".join(str(rec.get(k) or "") for k in ("title", "first_prompt", "project")).lower()
        if query.lower() not in hay:
            return False
    return True


def list_sessions(catalog_path=DEFAULT_CATALOG, **f):
    cat = load_catalog(catalog_path)
    rows = [r for r in cat.get("sessions", {}).values() if _match(r, **f)]
    rows.sort(key=lambda r: r.get("start") or "", reverse=True)
    return rows


def tag(catalog_path, session_id, tags, remove=False):
    cat = load_catalog(catalog_path)
    s = cat.get("sessions", {}).get(session_id)
    if not s:
        raise KeyError(session_id)
    cur = set(s.get("tags", []))
    cur = (cur - set(tags)) if remove else (cur | set(tags))
    s["tags"] = sorted(cur)
    save_catalog(cat, catalog_path)
    return s["tags"]


# ----------------------------------------------------------------- normalization
def _clip(s, n):
    s = str(s).replace("\r", "")
    return s if len(s) <= n else s[:n] + f"… [+{len(s)-n} chars]"


def _tool_summary(name, inp):
    inp = inp or {}
    if name == "Bash":
        return f"$ {inp.get('command','')}" + (f"   # {inp['description']}" if inp.get("description") else "")
    if name in ("Read", "Edit", "Write", "NotebookEdit"):
        return f"{name} {inp.get('file_path', inp.get('notebook_path',''))}"
    if name == "Agent":
        return f"Agent[{inp.get('subagent_type','?')}] {_clip(inp.get('description',''),80)}"
    keys = {k: _clip(v, 80) for k, v in inp.items() if k not in ("content",)}
    return f"{name} {json.dumps(keys, ensure_ascii=False)[:200]}"


def normalize_cc(path, max_output=500, include_thinking=False):
    out = []
    for o in _iter_json(path):
        t = o.get("type")
        msg = o.get("message", {}) or {}
        c = msg.get("content")
        if t == "user":
            if isinstance(c, str):
                out.append(("user", o.get("timestamp"), c.strip()))
            elif isinstance(c, list):
                for b in c:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        body = b.get("content")
                        if isinstance(body, list):
                            body = " ".join(x.get("text", "") for x in body if isinstance(x, dict))
                        err = b.get("is_error")
                        out.append(("result", o.get("timestamp"),
                                    ("ERROR " if err else "") + _clip(body, max_output * 3 if err else max_output)))
        elif t == "assistant":
            for b in (c if isinstance(c, list) else []):
                bt = b.get("type")
                if bt == "text" and b.get("text", "").strip():
                    out.append(("assistant", o.get("timestamp"), b["text"].strip()))
                elif bt == "thinking" and include_thinking and b.get("thinking", "").strip():
                    out.append(("thinking", o.get("timestamp"), _clip(b["thinking"], max_output)))
                elif bt == "tool_use":
                    out.append(("tool", o.get("timestamp"), _tool_summary(b.get("name"), b.get("input"))))
    return out


def normalize_codex(path, max_output=500, include_thinking=False):
    out = []
    for o in _iter_json(path):
        if o.get("type") != "event_msg":
            continue
        pl = o.get("payload", {}) or {}
        pt = pl.get("type", "")
        txt = pl.get("message") or pl.get("text") or pl.get("command") or pl.get("output")
        if not txt:
            continue
        role = "user" if "user" in pt else "assistant" if ("agent" in pt or "assistant" in pt) else \
               "tool" if ("command" in pt or "exec" in pt) else "result"
        out.append((role, o.get("timestamp"), _clip(txt, max_output)))
    return out


def ingest(session_ids, catalog_path=DEFAULT_CATALOG, fmt="md", max_output=500,
           include_thinking=False):
    """Normalize one or more sessions into a digest (markdown string or dict)."""
    cat = load_catalog(catalog_path)
    sess = cat.get("sessions", {})
    blocks = []
    for sid in session_ids:
        rec = sess.get(sid)
        if not rec:
            blocks.append({"id": sid, "error": "not in catalog (run: sessions index)"})
            continue
        norm = (normalize_cc if rec["source"] == "claude-code" else normalize_codex)(
            Path(rec["path"]), max_output, include_thinking)
        blocks.append({"meta": rec, "turns": norm})
    if fmt == "json":
        return {"sessions": blocks}
    return _render_md(blocks)


def _render_md(blocks):
    LABEL = {"user": "USER", "assistant": "ASSISTANT", "tool": "  ·tool", "result": "  ·result",
             "thinking": "  ·thinking"}
    lines = ["# Session digest (lossless-structured — distill this into research/session-harvest.md)\n"]
    for blk in blocks:
        if blk.get("error"):
            lines.append(f"## {blk['id']} — ERROR: {blk['error']}\n")
            continue
        m = blk["meta"]
        tools = ", ".join(f"{k}×{v}" for k, v in sorted(m.get("tools", {}).items(), key=lambda x: -x[1]))
        lines.append(f"## {m.get('title') or m['id']}")
        lines.append(f"- id: `{m['id']}` · source: {m['source']} · project: {m.get('project')}")
        lines.append(f"- time: {m.get('start')} → {m.get('end')} · git: {m.get('git_branch')}")
        lines.append(f"- turns: {m.get('user_turns')} user / {m.get('assistant_turns')} assistant · tools: {tools or '—'}")
        if m.get("tags"):
            lines.append(f"- tags: {', '.join(m['tags'])}")
        lines.append("")
        for role, _ts, text in blk["turns"]:
            prefix = LABEL.get(role, role)
            first, *rest = text.splitlines() or [""]
            lines.append(f"{prefix}: {first}")
            for r in rest:
                lines.append(f"    {r}")
        lines.append("\n---\n")
    return "\n".join(lines)
