#!/usr/bin/env python3
"""Semantic validation for playbook logical consistency.

Checks: role_mindset references, failure mode phase references,
phase ordering conventions, complexity profile validation.

Usage:
    python3 scripts/validate_semantic.py <playbook.json>
    python3 scripts/validate_semantic.py --help
"""

import argparse
import os
import json
import sys
from pathlib import Path
from typing import Tuple, List

# Tracing/Langfuse are OPTIONAL (audit 2026-09-18 F1): the validator must run in any environment.
try:
    import tracing  # noqa: F401
    from tracing import RunTrace
    from langfuse import observe, get_client
    _ws = os.environ.get("PBCPB_TRACE_WORKSPACE")
    if _ws:
        try:
            RunTrace.attach(_ws)
        except Exception:
            pass
except Exception:
    def observe(*_a, **_k):
        def _wrap(fn):
            return fn
        return _wrap

    def get_client(*_a, **_k):
        return None

    class RunTrace:  # type: ignore
        @staticmethod
        def attach(*_a, **_k):
            pass

        @staticmethod
        def current_trace_id():
            return None


def extract_role_name(role_mindset: str) -> str:
    """
    Extract role name from role_mindset string.

    Handles both em-dash (—) and regular dash (-) separators.
    """
    if " — " in role_mindset:
        return role_mindset.split(" — ")[0].strip()
    if " - " in role_mindset:
        return role_mindset.split(" - ")[0].strip()
    return role_mindset.strip()


def validate_semantic(playbook: dict) -> Tuple[List[str], List[str]]:
    """
    Validate semantic consistency of playbook.

    Returns:
        Tuple of (errors, warnings)
    """
    errors = []
    warnings = []

    # 1. Role mindset references existing role (case-insensitive)
    roles = playbook.get("roles", {})
    defined_roles_lower = {r.lower(): r for r in roles.keys()}

    for i, phase in enumerate(playbook.get("checklists", [])):
        comp = phase.get("compilation", {})
        role_mindset = comp.get("role_mindset", "")
        phase_title = phase.get("title", f"Phase {i}")

        if not role_mindset:
            continue

        role_name = extract_role_name(role_mindset)

        if role_name and role_name.lower() not in defined_roles_lower:
            errors.append(
                f"{phase_title}: role_mindset '{role_mindset}' references undefined role '{role_name}'"
            )

    # 2. Failure mode phase references exist
    failure_modes = playbook.get("failure_modes", [])
    phase_titles = set(p.get("title", "") for p in playbook.get("checklists", []))

    for fm in failure_modes:
        fm_id = fm.get("id", "Unknown")
        fm_phase = fm.get("phase", "")

        if fm_phase and fm_phase not in phase_titles:
            errors.append(
                f"Failure mode {fm_id}: references non-existent phase '{fm_phase}'"
            )

    # 3. Phase ordering follows convention
    for i, phase in enumerate(playbook.get("checklists", [])):
        title = phase.get("title", "")
        expected_prefix = f"Phase {i}"

        if not title.startswith(expected_prefix):
            warnings.append(
                f"Phase {i} title '{title}' doesn't follow 'Phase N: Name' pattern"
            )

    # 4. Complexity profile validation (if present)
    profile = playbook.get("complexity_profile", {})
    if profile:
        classification = profile.get("classification")
        valid_classifications = {"simple", "moderate", "complex", "structured"}
        if classification and classification not in valid_classifications:
            errors.append(
                f"complexity_profile.classification '{classification}' not in {valid_classifications}"
            )

        expected_phases = profile.get("expected_phases")
        if expected_phases is not None:
            if not isinstance(expected_phases, int) or expected_phases < 1:
                errors.append("complexity_profile.expected_phases must be positive integer")

    return errors, warnings


@observe(name="validate-semantic", capture_input=False, capture_output=False)
def _run_validate_semantic(path: str) -> tuple[list, list]:
    """Run semantic validation and record span with result summary."""
    _lf = get_client()
    if _lf:
        _lf.update_current_span(input={"playbook": path})
    playbook = json.loads(Path(path).read_text())
    errors, warnings = validate_semantic(playbook)
    if _lf:
        _lf.update_current_span(output={"errors": len(errors), "warnings": len(warnings), "passed": len(errors) == 0})
    return errors, warnings


def main():
    parser = argparse.ArgumentParser(
        description="Validate semantic consistency of a playbook JSON file.",
        epilog="Examples:\n"
               "  python3 scripts/validate_semantic.py my-playbook.json\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "playbook",
        nargs="?",
        default="playbook-creator-playbook.json",
        help="Path to the playbook JSON file (default: playbook-creator-playbook.json)",
    )
    args = parser.parse_args()

    path = args.playbook
    if not Path(path).exists():
        print(f"File not found: {path}")
        sys.exit(1)

    import re as _re
    _tid = RunTrace.current_trace_id()
    if not (_tid and _re.fullmatch(r"[0-9a-f]{32}", str(_tid))):
        _tid = None
    if _tid is None:
        _fn = getattr(_run_validate_semantic, "__wrapped__", _run_validate_semantic)
        errors, warnings = _fn(path)
    else:
        errors, warnings = _run_validate_semantic(path, langfuse_trace_id=_tid)

    if errors:
        print(f"FAIL: {len(errors)} error(s), {len(warnings)} warning(s)")
        for e in errors:
            print(f"  ERROR: {e}")
        for w in warnings:
            print(f"  WARN: {w}")
        sys.exit(1)
    elif warnings:
        print(f"PASS with {len(warnings)} warning(s)")
        for w in warnings:
            print(f"  WARN: {w}")
        sys.exit(0)
    else:
        print("PASS: All semantic checks passed")
        sys.exit(0)


if __name__ == "__main__":
    main()
