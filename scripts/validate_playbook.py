#!/usr/bin/env python3
"""Structural validator for playbook JSON files.

Checks: JSON syntax, required top-level fields, type/enum validation,
checklist structure, [Role] consistency, compilation blocks, handoff blocks,
owner fields, scope/usage/KB structure, metrics completeness, phase count
consistency, handoff chain consistency, artifact provenance.

Optional: jsonschema validation against templates/output-schema.json.

Usage:
    python3 scripts/validate_playbook.py <playbook.json>
    python3 scripts/validate_playbook.py <playbook.json> --schema templates/output-schema.json
    python3 scripts/validate_playbook.py --help
"""
import argparse
import os
import json
import re
import sys
from pathlib import Path
from typing import Tuple, List

# Ensure project root is on sys.path so 'tracing' module is importable.
sys.path.insert(0, str(Path(__file__).parent.parent))
# Add scripts path for compilation module imports.
sys.path.insert(0, str(Path(__file__).parent))

# Tracing/Langfuse are OPTIONAL (audit 2026-09-18 F1): the validator must run in any environment.
try:
    import tracing  # noqa: F401 — initialise Langfuse before decorators fire
    from tracing import RunTrace
    from langfuse import observe, get_client
    _ws = os.environ.get("PBCPB_TRACE_WORKSPACE")
    if _ws:
        try:
            RunTrace.attach(_ws)
        except Exception:
            pass
except Exception:  # tracing module or langfuse unavailable -> no-op shims
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

# The compilation engine is optional in the public release (audit-driven minimal build). If it is
# not present, the context-budget feasibility check degrades to a warning; all other checks run.
try:
    from compilation.context_budget import estimate_context_tokens, estimate_critical_tokens
    _HAVE_COMPILATION = True
except Exception:
    _HAVE_COMPILATION = False

    def estimate_context_tokens(*_a, **_k):
        return 0

    def estimate_critical_tokens(*_a, **_k):
        return 0

REQUIRED_TOP_LEVEL = [
    "title", "version", "description", "workflow_model", "roles",
    "scope", "cross_cutting_concerns", "knowledge_base", "checklists",
    "metrics", "usage_instructions", "failure_modes",
    "phase_kb_mapping", "skill_activation", "router", "context_preservation"
]

REQUIRED_COMPILATION = [
    "context_load", "role_mindset", "objective", "pre_check",
    "failure_modes_relevant"
]

REQUIRED_HANDOFF = [
    "output_artifacts", "next_phase_context"
]

VALID_CONTEXT_UPDATE_ACTIONS = {"append", "update", "create"}

VALID_SEVERITIES = {"crash", "error", "degraded", "cosmetic"}

VALID_WORKFLOW_MODELS = {
    "human-in-the-loop", "fully-autonomous", "human-directed",
    "role-based-single-agent", "role-based-multi-agent"
}

VALID_METRIC_TYPES = {"metric_integer", "metric_currency", "metric_duration"}
VALID_METRIC_CATEGORIES = {"process", "output_quality", "domain_outcome"}

FM_ID_PATTERN = re.compile(r"^FM-\d{3}$")
MET_ID_PATTERN = re.compile(r"^MET-\d{2}$")
CCC_ID_PATTERN = re.compile(r"^CCC-\d{2}$")
VALID_ENFORCEMENT_METHODS = {
    "checklist_items", "gate_condition", "compilation_precheck", "task_description"
}

VALID_CRITICAL_THRESHOLDS = range(1, 11)  # 1-10

# Behavioral profile valid values
VALID_RISK_TOLERANCE = {"minimal", "low", "moderate", "high"}
VALID_CREATIVITY_LEVEL = {"strict", "conservative", "moderate", "exploratory"}
VALID_VERBOSITY = {"minimal", "concise", "detailed", "comprehensive"}
VALID_STANCE = {"supportive", "neutral", "critical", "adversarial"}


def _normalize_role(role: str) -> str:
    """Normalize a role name for comparison: strip whitespace."""
    return role.strip()


def _roles_match(role_a: str, role_b: str) -> bool:
    """Case-insensitive, whitespace-tolerant role comparison."""
    return _normalize_role(role_a).lower() == _normalize_role(role_b).lower()


def _find_role_in_defined(role: str, defined_roles: set) -> str | None:
    """Find the canonical form of a role in defined_roles (case-insensitive).
    Returns the canonical name or None if not found."""
    norm = _normalize_role(role).lower()
    for defined in defined_roles:
        if defined.lower() == norm:
            return defined
    return None


def validate_context_budget_feasibility(
    data: dict, errors: list, warnings: list
):
    """Check that context_load sizes are realistic for configured budget."""
    defaults = data.get("defaults", {})
    budget = defaults.get("context_budget_tokens", 64000)
    system_budget = defaults.get("system_prompt_budget", 2000)
    response_budget = defaults.get("max_tokens", 4096)
    threshold = defaults.get("critical_priority_threshold", 3)

    available_for_files = budget - system_budget - response_budget

    for i, phase in enumerate(data.get("checklists", [])):
        comp = phase.get("compilation", {})
        ctx_load = comp.get("context_load", [])
        ctx_budget = comp.get("context_budget", {})
        phase_title = phase.get("title", f"Phase {i}")

        if not ctx_load:
            continue

        estimated_tokens = estimate_context_tokens(ctx_load)
        priority = ctx_budget.get("priority", {})
        critical_tokens = estimate_critical_tokens(ctx_load, priority, threshold)

        if critical_tokens > available_for_files:
            errors.append(
                f"{phase_title}: Critical files ({critical_tokens} tokens estimated) exceed "
                f"available budget ({available_for_files} tokens)"
            )

        if estimated_tokens > available_for_files * 1.5:
            warnings.append(
                f"{phase_title}: context_load ({estimated_tokens} tokens estimated) "
                f"may significantly exceed budget ({available_for_files} available)"
            )


def validate_schema(data: dict, schema_path: str) -> Tuple[List[str], List[str]]:
    """Validate playbook against JSON Schema. Returns (errors, warnings)."""
    errors = []
    warnings = []
    try:
        import jsonschema
    except ImportError:
        warnings.append(
            "jsonschema not installed — skipping schema validation. "
            "Install with: pip install jsonschema"
        )
        return errors, warnings

    try:
        schema = json.loads(Path(schema_path).read_text())
    except (FileNotFoundError, json.JSONDecodeError) as e:
        errors.append(f"Cannot load schema '{schema_path}': {e}")
        return errors, warnings

    validator = jsonschema.Draft7Validator(schema)
    for error in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
        path = ".".join(str(p) for p in error.absolute_path) or "(root)"
        # F5: for oneOf/anyOf failures, surface the most specific sub-schema error (which field/type
        # actually failed) instead of the unhelpful "is not valid under any of the given schemas".
        if error.context:
            best = jsonschema.exceptions.best_match(error.context)
            sub = ".".join(str(p) for p in best.absolute_path)
            where = f"{path}.{sub}" if sub else path
            errors.append(f"Schema: {where}: {best.message}")
        else:
            errors.append(f"Schema: {path}: {error.message}")

    return errors, warnings


def validate(path: str, schema_path: str = None) -> Tuple[List[str], List[str]]:
    """Validate a playbook file. Returns (errors, warnings) as separate lists."""
    errors = []
    warnings = []

    # 1. JSON syntax
    try:
        with open(path) as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return [f"JSON parse error: {e}"], []

    # 1b. Optional jsonschema validation
    if schema_path:
        schema_errors, schema_warnings = validate_schema(data, schema_path)
        errors.extend(schema_errors)
        warnings.extend(schema_warnings)

    # 2. Required top-level fields
    for field in REQUIRED_TOP_LEVEL:
        if field not in data:
            errors.append(f"Missing top-level field: {field}")

    if errors:
        return errors, warnings  # Can't continue without structure

    # 2b. Type and enum checks on top-level fields
    if not isinstance(data.get("version"), int) or data["version"] < 1:
        errors.append(f"version must be integer >= 1, got {data.get('version')!r}")

    wm = data.get("workflow_model", "")
    if wm not in VALID_WORKFLOW_MODELS:
        errors.append(f"workflow_model '{wm}' not in {sorted(VALID_WORKFLOW_MODELS)}")

    # 2c. Validate defaults section if present
    defaults = data.get("defaults", {})
    if defaults:
        if not isinstance(defaults, dict):
            errors.append("defaults must be an object")
        else:
            if "model" in defaults and not isinstance(defaults["model"], str):
                errors.append("defaults.model must be a string")

            if "temperature" in defaults:
                temp = defaults["temperature"]
                if not isinstance(temp, (int, float)) or temp < 0 or temp > 2:
                    errors.append("defaults.temperature must be a number between 0 and 2")

            if "max_tokens" in defaults:
                mt = defaults["max_tokens"]
                if not isinstance(mt, int) or mt < 256:
                    errors.append("defaults.max_tokens must be an integer >= 256")

            if "context_budget_tokens" in defaults:
                cbt = defaults["context_budget_tokens"]
                if not isinstance(cbt, int) or cbt < 1000:
                    errors.append("defaults.context_budget_tokens must be an integer >= 1000")

            if "system_prompt_budget" in defaults:
                spb = defaults["system_prompt_budget"]
                if not isinstance(spb, int) or spb < 500:
                    errors.append("defaults.system_prompt_budget must be an integer >= 500")

            if "critical_priority_threshold" in defaults:
                cpt = defaults["critical_priority_threshold"]
                if not isinstance(cpt, int) or cpt < 1 or cpt > 10:
                    errors.append("defaults.critical_priority_threshold must be an integer between 1 and 10")

            if "model_fallbacks" in defaults:
                mf = defaults["model_fallbacks"]
                if not isinstance(mf, dict):
                    errors.append("defaults.model_fallbacks must be an object")
                else:
                    for model, fallbacks in mf.items():
                        if not isinstance(fallbacks, list):
                            errors.append(f"defaults.model_fallbacks['{model}'] must be an array")
                        elif not all(isinstance(f, str) for f in fallbacks):
                            errors.append(f"defaults.model_fallbacks['{model}'] must contain strings")

    # 3. Roles defined
    roles_data = data.get("roles", {})
    defined_roles = set(roles_data.keys())
    if not defined_roles:
        errors.append("No roles defined")

    # 3b. Role format validation (string or object)
    for role_name, role_def in roles_data.items():
        if isinstance(role_def, str):
            pass  # String format - backward compatible
        elif isinstance(role_def, dict):
            if "description" not in role_def:
                errors.append(f"Role '{role_name}' object missing 'description'")

            if "defaults" in role_def:
                role_defaults = role_def["defaults"]
                if not isinstance(role_defaults, dict):
                    errors.append(f"Role '{role_name}' defaults must be an object")
                else:
                    if "model" in role_defaults and not isinstance(role_defaults["model"], str):
                        errors.append(f"Role '{role_name}' defaults.model must be a string")

                    if "temperature" in role_defaults:
                        temp = role_defaults["temperature"]
                        if isinstance(temp, list):
                            if len(temp) != 2:
                                errors.append(f"Role '{role_name}' temperature range must have 2 elements")
                            elif not all(isinstance(t, (int, float)) for t in temp):
                                errors.append(f"Role '{role_name}' temperature range values must be numbers")
                            elif temp[0] < 0 or temp[0] > 2 or temp[1] < 0 or temp[1] > 2:
                                errors.append(f"Role '{role_name}' temperature range must be within 0-2")
                        elif not isinstance(temp, (int, float)):
                            errors.append(f"Role '{role_name}' temperature must be a number or range")
                        elif temp < 0 or temp > 2:
                            errors.append(f"Role '{role_name}' temperature must be between 0 and 2")

            if "role_context" in role_def:
                if not isinstance(role_def["role_context"], str):
                    errors.append(f"Role '{role_name}' role_context must be a string")

            if "agent_assignment" in role_def:
                if not isinstance(role_def["agent_assignment"], str):
                    errors.append(f"Role '{role_name}' agent_assignment must be a string")
        else:
            errors.append(f"Role '{role_name}' must be a string or object")

    # 4. Checklists structure
    role_usage: dict[str, int] = {}  # canonical role name -> count
    checklists = data.get("checklists", [])

    if not checklists:
        errors.append("checklists[] is empty")

    for i, phase in enumerate(checklists):
        phase_label = phase.get("title", f"checklist[{i}]")

        if "title" not in phase:
            errors.append(f"checklist[{i}]: missing title")
        if "purpose" not in phase:
            errors.append(f"{phase_label}: missing purpose")

        # Compilation block
        comp = phase.get("compilation")
        if comp is None:
            errors.append(f"{phase_label}: missing compilation block")
        else:
            for field in REQUIRED_COMPILATION:
                if field not in comp:
                    errors.append(f"{phase_label}: compilation missing '{field}'")

            # Persistent files check (skip Phase 0)
            if i > 0 and comp:
                ctx = comp.get("context_load", [])
                ctx_str = " ".join(ctx).lower()
                if "decisions-ledger" not in ctx_str:
                    errors.append(f"{phase_label}: context_load missing decisions-ledger.md")
                if "artifact-manifest" not in ctx_str:
                    errors.append(f"{phase_label}: context_load missing artifact-manifest.md")

            # Validate agent_config
            agent_config = comp.get("agent_config", {})
            if agent_config:
                if not isinstance(agent_config, dict):
                    errors.append(f"{phase_label}: agent_config must be an object")
                else:
                    if "model" in agent_config and not isinstance(agent_config["model"], str):
                        errors.append(f"{phase_label}: agent_config.model must be a string")
                    if "temperature" in agent_config:
                        temp = agent_config["temperature"]
                        if not isinstance(temp, (int, float)) or temp < 0 or temp > 2:
                            errors.append(f"{phase_label}: agent_config.temperature must be 0-2")
                    if "max_tokens" in agent_config:
                        mt = agent_config["max_tokens"]
                        if not isinstance(mt, int) or mt < 256:
                            errors.append(f"{phase_label}: agent_config.max_tokens must be >= 256")

            # Validate system_prompt_auto flags
            spa = comp.get("system_prompt_auto", {})
            if spa:
                if not isinstance(spa, dict):
                    errors.append(f"{phase_label}: system_prompt_auto must be an object")
                else:
                    for flag_name in ["role_definition", "phase_objective", "failure_modes",
                                      "pre_check_guidance", "context_files", "handoff_requirements"]:
                        if flag_name in spa and not isinstance(spa[flag_name], bool):
                            errors.append(f"{phase_label}: system_prompt_auto.{flag_name} must be boolean")

            # Validate context_budget
            ctx_budget = comp.get("context_budget", {})
            if ctx_budget:
                if not isinstance(ctx_budget, dict):
                    errors.append(f"{phase_label}: context_budget must be an object")
                else:
                    if "max_tokens" in ctx_budget:
                        mt = ctx_budget["max_tokens"]
                        if not isinstance(mt, int) or mt < 1000:
                            errors.append(f"{phase_label}: context_budget.max_tokens must be >= 1000")

                    priority = ctx_budget.get("priority", {})
                    if priority:
                        if not isinstance(priority, dict):
                            errors.append(f"{phase_label}: context_budget.priority must be an object")
                        else:
                            ctx_load_files = set()
                            for item in comp.get("context_load", []):
                                base = re.split(r"\s*\(", item)[0].strip()
                                ctx_load_files.add(base)
                            for filename, prio_val in priority.items():
                                if not isinstance(prio_val, int) or prio_val < 1 or prio_val > 10:
                                    errors.append(f"{phase_label}: priority for '{filename}' must be integer 1-10")
                                prio_base = re.split(r"\s*\(", filename)[0].strip()
                                if prio_base not in ctx_load_files:
                                    errors.append(f"{phase_label}: priority file '{filename}' not in context_load")

            # Validate skill_preparation
            if "skill_preparation" in comp:
                sp = comp["skill_preparation"]
                if not isinstance(sp, str):
                    errors.append(f"{phase_label}: skill_preparation must be a string")

            # Validate success_criteria
            if "success_criteria" in comp:
                sc = comp["success_criteria"]
                if not isinstance(sc, list):
                    errors.append(f"{phase_label}: success_criteria must be an array")
                elif not all(isinstance(c, str) for c in sc):
                    errors.append(f"{phase_label}: success_criteria must contain strings")
                elif len(sc) == 0:
                    errors.append(f"{phase_label}: success_criteria must not be empty if present")

            # Validate tools_available
            if "tools_available" in comp:
                ta = comp["tools_available"]
                if not isinstance(ta, list):
                    errors.append(f"{phase_label}: tools_available must be an array")
                elif not all(isinstance(t, str) for t in ta):
                    errors.append(f"{phase_label}: tools_available must contain strings")
                elif len(ta) == 0:
                    errors.append(f"{phase_label}: tools_available must not be empty if present")

            # Validate behavioral_profile
            if "behavioral_profile" in comp:
                bp = comp["behavioral_profile"]
                if not isinstance(bp, dict):
                    errors.append(f"{phase_label}: behavioral_profile must be an object")
                else:
                    if "risk_tolerance" in bp and bp["risk_tolerance"] not in VALID_RISK_TOLERANCE:
                        errors.append(f"{phase_label}: behavioral_profile.risk_tolerance '{bp['risk_tolerance']}' not in {sorted(VALID_RISK_TOLERANCE)}")
                    if "creativity_level" in bp and bp["creativity_level"] not in VALID_CREATIVITY_LEVEL:
                        errors.append(f"{phase_label}: behavioral_profile.creativity_level '{bp['creativity_level']}' not in {sorted(VALID_CREATIVITY_LEVEL)}")
                    if "verbosity" in bp and bp["verbosity"] not in VALID_VERBOSITY:
                        errors.append(f"{phase_label}: behavioral_profile.verbosity '{bp['verbosity']}' not in {sorted(VALID_VERBOSITY)}")
                    if "stance" in bp and bp["stance"] not in VALID_STANCE:
                        errors.append(f"{phase_label}: behavioral_profile.stance '{bp['stance']}' not in {sorted(VALID_STANCE)}")

        # Items
        items = phase.get("items", [])
        if not items:
            errors.append(f"{phase_label}: items[] is empty")

        has_gate = False
        for j, item in enumerate(items):
            title = item.get("title", "")
            item_label = f"{phase_label} item[{j}]"

            # Owner field — required on ALL items including gates
            if "owner" not in item:
                errors.append(f"{item_label}: missing owner field")

            if not title:
                errors.append(f"{item_label}: missing title")
                continue

            # [Role] extraction — normalized matching
            role_match = re.match(r"\[([^\]]+)\]", title)
            if not role_match:
                errors.append(f"{item_label}: title doesn't start with [Role]: {title[:50]}")
            else:
                role_raw = role_match.group(1)
                canonical = _find_role_in_defined(role_raw, defined_roles)
                if canonical:
                    role_usage[canonical] = role_usage.get(canonical, 0) + 1
                else:
                    # Track as-is for the undefined-role error below
                    role_usage[role_raw] = role_usage.get(role_raw, 0) + 1

                # Owner consistency — normalized
                owner = item.get("owner", "")
                owner_match = re.match(r"\[([^\]]+)\]", owner)
                if owner and owner_match:
                    if not _roles_match(role_raw, owner_match.group(1)):
                        errors.append(f"{item_label}: owner '{owner}' doesn't match title role '[{role_raw}]'")
                elif owner and not owner_match:
                    errors.append(f"{item_label}: owner '{owner}' should use [Role] format")

            # Gate detection
            if "gate_conditions" in item:
                has_gate = True
                if not isinstance(item["gate_conditions"], list):
                    errors.append(f"{item_label}: gate_conditions must be array")
                if "blocker_examples" not in item:
                    errors.append(f"{item_label}: gate missing blocker_examples")
                if "guardrail_checks" in item:
                    gc = item["guardrail_checks"]
                    if not isinstance(gc, list):
                        errors.append(f"{item_label}: guardrail_checks must be an array")
                    elif not all(isinstance(g, str) for g in gc):
                        errors.append(f"{item_label}: guardrail_checks must contain strings")

                if "handoff" not in item:
                    errors.append(f"{item_label}: gate missing handoff block")
                else:
                    handoff = item["handoff"]
                    for field in REQUIRED_HANDOFF:
                        if field not in handoff:
                            errors.append(f"{item_label}: handoff missing '{field}'")

                    if "excluded_files" in handoff:
                        ef = handoff["excluded_files"]
                        if not isinstance(ef, list):
                            errors.append(f"{item_label}: excluded_files must be an array")
                        elif not all(isinstance(f, str) for f in ef):
                            errors.append(f"{item_label}: excluded_files must contain strings")

                    if "context_update" in handoff:
                        cu = handoff["context_update"]
                        if not isinstance(cu, dict):
                            errors.append(f"{item_label}: context_update must be an object")
                        else:
                            for fname, action in cu.items():
                                if action not in VALID_CONTEXT_UPDATE_ACTIONS:
                                    errors.append(f"{item_label}: context_update['{fname}'] action '{action}' not in {VALID_CONTEXT_UPDATE_ACTIONS}")

                    if "skill_validation" in handoff:
                        sv = handoff["skill_validation"]
                        if not isinstance(sv, str):
                            errors.append(f"{item_label}: skill_validation must be a string")

                    # Deprecation warnings (proper warnings, not errors)
                    if "excluded_context" in handoff:
                        warnings.append(f"{item_label}: excluded_context is deprecated, use excluded_files")

                    if "skill" in handoff:
                        warnings.append(f"{item_label}: skill is deprecated, use skill_validation")

                    if "metrics_snapshot" in handoff:
                        ms = handoff["metrics_snapshot"]
                        if not isinstance(ms, dict):
                            errors.append(f"{item_label}: metrics_snapshot must be an object")
                        else:
                            if "collect" not in ms:
                                errors.append(f"{item_label}: metrics_snapshot missing 'collect'")
                            elif not isinstance(ms["collect"], list):
                                errors.append(f"{item_label}: metrics_snapshot.collect must be an array")
                            if "record_in" not in ms:
                                errors.append(f"{item_label}: metrics_snapshot missing 'record_in'")
                            elif not isinstance(ms["record_in"], str):
                                errors.append(f"{item_label}: metrics_snapshot.record_in must be a string")

                    if "kb_status" in handoff:
                        ks = handoff["kb_status"]
                        if not isinstance(ks, dict):
                            errors.append(f"{item_label}: kb_status must be an object")
                        else:
                            for field in ("total_entries", "harvested", "placeholder"):
                                if field in ks and not isinstance(ks[field], (int, type(None))):
                                    errors.append(f"{item_label}: kb_status.{field} must be an integer or null")

        if not has_gate and i < len(checklists) - 1:
            errors.append(f"{phase_label}: no gate task found")

    # 5. Role consistency — using normalized matching
    for role, count in role_usage.items():
        if not _find_role_in_defined(role, defined_roles):
            errors.append(f"Role [{role}] used in tasks but not defined in roles{{}}")
        if count < 3:
            warnings.append(f"Role [{role}] appears only {count} time(s) (minimum 3 recommended)")

    for role in defined_roles:
        if role not in role_usage:
            errors.append(f"Role [{role}] defined but never used in any task")

    # 6. Metrics
    metrics = data.get("metrics", [])
    if not metrics:
        errors.append("metrics[] is empty")
    else:
        categories = {m.get("category") for m in metrics}
        for req in ("process", "output_quality", "domain_outcome"):
            if req not in categories:
                errors.append(f"Missing metric category: {req}")

    # 7. Failure modes
    fm = data.get("failure_modes", None)
    if fm is None:
        errors.append("failure_modes field missing")
    elif fm:
        fm_ids = set()
        for entry in fm:
            for field in ("id", "symptom", "root_cause", "fix", "prevention", "phase", "severity", "source"):
                if field not in entry:
                    errors.append(f"failure_mode {entry.get('id', '?')}: missing '{field}'")
            if entry.get("severity") and entry["severity"] not in VALID_SEVERITIES:
                errors.append(f"failure_mode {entry.get('id')}: invalid severity '{entry['severity']}'")
            fid = entry.get("id")
            if fid and not FM_ID_PATTERN.match(fid):
                errors.append(
                    f"failure_mode '{fid}': id must match FM-NNN format "
                    f"(three digits, e.g., FM-001, FM-025)"
                )
            if fid in fm_ids:
                errors.append(f"Duplicate FM-ID: {fid}")
            fm_ids.add(fid)

    # 8. Router
    router = data.get("router", {})
    for field in ("description", "decision_tree", "default"):
        if field not in router:
            errors.append(f"router missing '{field}'")

    # 9. Context preservation
    cp = data.get("context_preservation", {})
    for field in ("decisions_ledger", "artifact_manifest", "rules"):
        if field not in cp:
            errors.append(f"context_preservation missing '{field}'")

    # 10. Scope structure
    scope = data.get("scope", {})
    for field in ("in_scope", "out_of_scope", "adjacent"):
        if field not in scope:
            errors.append(f"scope missing '{field}'")

    # 11. Usage instructions structure
    ui = data.get("usage_instructions", {})
    for field in ("how_to_run", "session_strategy", "cost_optimization", "post_run_review"):
        if field not in ui:
            errors.append(f"usage_instructions missing '{field}'")
    if "post_run_review" in ui and "assess" not in ui["post_run_review"]:
        errors.append("usage_instructions.post_run_review missing 'assess'")

    # 12. Knowledge base required fields
    kb = data.get("knowledge_base", {})
    if "complexity" not in kb:
        errors.append("knowledge_base missing 'complexity'")
    elif kb["complexity"] not in ("flat", "structured"):
        errors.append(f"knowledge_base.complexity '{kb['complexity']}' not in ['flat', 'structured']")
    if "directory_structure" not in kb:
        errors.append("knowledge_base missing 'directory_structure'")

    # 13. Metrics completeness and enum validation
    for m in metrics:
        if "measurement_method" not in m:
            errors.append(f"metric '{m.get('title', '?')}' missing measurement_method")
        mt = m.get("type", "")
        if mt and mt not in VALID_METRIC_TYPES:
            errors.append(f"metric '{m.get('title', '?')}': type '{mt}' not in {sorted(VALID_METRIC_TYPES)}")
        mc = m.get("category", "")
        if mc and mc not in VALID_METRIC_CATEGORIES:
            errors.append(f"metric '{m.get('title', '?')}': category '{mc}' not in {sorted(VALID_METRIC_CATEGORIES)}")

    # 13b. Metric ID validation (required for version >= 3)
    met_ids = set()
    version = data.get("version", 1)
    for m in metrics:
        mid = m.get("id")
        if mid:
            if not MET_ID_PATTERN.match(mid):
                errors.append(
                    f"metric '{m.get('title', '?')}': id '{mid}' must match MET-NN format "
                    f"(two digits, e.g., MET-01, MET-12)"
                )
            if mid in met_ids:
                errors.append(f"Duplicate MET-ID: {mid}")
            met_ids.add(mid)
        elif version >= 3:
            errors.append(
                f"metric '{m.get('title', '?')}': missing id (required for version >= 3, format: MET-NN)"
            )

    # 13c. Validate metrics_snapshot references
    for i, phase in enumerate(checklists):
        phase_label = phase.get("title", f"checklist[{i}]")
        for j, item in enumerate(phase.get("items", [])):
            ms = item.get("handoff", {}).get("metrics_snapshot", {})
            if ms and "collect" in ms and isinstance(ms["collect"], list) and met_ids:
                for ref in ms["collect"]:
                    if ref not in met_ids:
                        errors.append(f"{phase_label} item[{j}]: metrics_snapshot references unknown metric '{ref}'")

    # 14. Cross-cutting concerns non-empty + object validation
    ccc = data.get("cross_cutting_concerns", [])
    if not ccc:
        errors.append("cross_cutting_concerns is empty")
    else:
        ccc_ids = set()
        for idx, item in enumerate(ccc):
            if isinstance(item, str):
                continue
            elif isinstance(item, dict):
                for req_field in ("id", "title", "description", "enforcement_method", "minimum_phases"):
                    if req_field not in item:
                        errors.append(f"cross_cutting_concerns[{idx}]: missing '{req_field}'")
                ccc_id = item.get("id", "")
                if ccc_id:
                    if not CCC_ID_PATTERN.match(ccc_id):
                        errors.append(
                            f"cross_cutting_concerns[{idx}]: id '{ccc_id}' must match CCC-NN format "
                            f"(two digits, e.g., CCC-01)"
                        )
                    if ccc_id in ccc_ids:
                        errors.append(f"Duplicate CCC-ID: {ccc_id}")
                    ccc_ids.add(ccc_id)
                em = item.get("enforcement_method", "")
                if em and em not in VALID_ENFORCEMENT_METHODS:
                    errors.append(f"cross_cutting_concerns[{idx}]: enforcement_method '{em}' not valid")
                min_phases = item.get("minimum_phases", 0)
                phases_applied = item.get("phases_applied", [])
                if isinstance(min_phases, int) and isinstance(phases_applied, list):
                    if len(phases_applied) < min_phases:
                        errors.append(
                            f"cross_cutting_concerns[{idx}] ({ccc_id}): "
                            f"phases_applied has {len(phases_applied)} entries, minimum_phases is {min_phases}"
                        )
            else:
                errors.append(f"cross_cutting_concerns[{idx}]: must be string or object")

    # 15. Phase count consistency (phase_kb_mapping and skill_activation)
    num_phases = len(checklists)
    if len(data.get("phase_kb_mapping", {})) != num_phases:
        errors.append(f"phase_kb_mapping has {len(data.get('phase_kb_mapping', {}))} keys, expected {num_phases}")
    if len(data.get("skill_activation", {})) != num_phases:
        errors.append(f"skill_activation has {len(data.get('skill_activation', {}))} keys, expected {num_phases}")

    # 16. Handoff chain consistency
    persistent = {"decisions-ledger", "artifact-manifest", "metrics-tracker"}
    for i in range(1, len(checklists)):
        prev = checklists[i - 1]
        curr = checklists[i]
        prev_label = prev.get("title", f"checklist[{i-1}]")
        curr_label = curr.get("title", f"checklist[{i}]")

        prev_next = set()
        for item in prev.get("items", []):
            handoff = item.get("handoff", {})
            if "next_phase_context" in handoff:
                for f in handoff["next_phase_context"]:
                    base = re.split(r"\s*\(", f)[0].strip().lower()
                    prev_next.add(base)

        if not prev_next:
            continue

        curr_comp = curr.get("compilation", {})
        curr_ctx = curr_comp.get("context_load", [])
        for f in curr_ctx:
            base = re.split(r"\s*\(", f)[0].strip().lower()
            if any(p in base for p in persistent):
                continue
            if base not in prev_next:
                warnings.append(
                    f"{curr_label}: context_load has '{f}' not in {prev_label} next_phase_context"
                )

    # 17. Artifact provenance
    all_artifacts: set[str] = set()
    for i, phase in enumerate(checklists):
        phase_label = phase.get("title", f"checklist[{i}]")

        if i > 0:
            curr_comp = phase.get("compilation", {})
            for f in curr_comp.get("context_load", []):
                base = re.split(r"\s*\(", f)[0].strip().lower()
                if any(p in base for p in persistent):
                    continue
                if base not in all_artifacts:
                    warnings.append(
                        f"{phase_label}: context_load has '{f}' not in any prior output_artifacts"
                    )

        for item in phase.get("items", []):
            handoff = item.get("handoff", {})
            for a in handoff.get("output_artifacts", []):
                base = re.split(r"\s*\(", a)[0].strip().lower()
                all_artifacts.add(base)
        for item in phase.get("items", []):
            out = item.get("output", "")
            if out:
                for part in out.split(","):
                    base = re.split(r"\s*\(", part)[0].strip().lower()
                    all_artifacts.add(base)

    # 18. Context budget feasibility check
    validate_context_budget_feasibility(data, errors, warnings)

    # 19. Success criteria / gate_conditions cross-validation
    for i, phase in enumerate(checklists):
        phase_label = phase.get("title", f"checklist[{i}]")
        comp = phase.get("compilation", {})
        success_criteria = comp.get("success_criteria", [])
        if not success_criteria:
            continue

        gate_conditions = []
        for item in phase.get("items", []):
            if "gate_conditions" in item:
                gate_conditions = item["gate_conditions"]
                break

        if gate_conditions and success_criteria:
            sc_count = len(success_criteria)
            gc_count = len(gate_conditions)
            if sc_count > 0 and gc_count > 0:
                ratio = sc_count / gc_count if gc_count > 0 else 0
                if ratio < 0.3 or ratio > 3.0:
                    warnings.append(
                        f"{phase_label}: success_criteria ({sc_count} items) differs significantly "
                        f"from gate_conditions ({gc_count} items) — verify alignment"
                    )

    return errors, warnings


@observe(name="validate-playbook", capture_input=False, capture_output=False)
def _run_validate(path: str, schema_path: str | None) -> tuple[list, list]:
    """Run validation and record span with result summary."""
    _lf = get_client()
    if _lf:
        _lf.update_current_span(input={"playbook": path, "schema": schema_path})
    errors, warnings = validate(path, schema_path=schema_path)
    if _lf:
        _lf.update_current_span(output={"errors": len(errors), "warnings": len(warnings), "passed": len(errors) == 0})
    return errors, warnings


def main():
    parser = argparse.ArgumentParser(
        description="Validate a playbook JSON file for structural correctness.",
        epilog="Examples:\n"
               "  python3 scripts/validate_playbook.py my-playbook.json\n"
               "  python3 scripts/validate_playbook.py my-playbook.json --schema templates/output-schema.json\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "playbook",
        nargs="?",
        default="playbook-creator-playbook.json",
        help="Path to the playbook JSON file (default: playbook-creator-playbook.json)",
    )
    parser.add_argument(
        "--schema",
        default=None,
        help="Path to JSON Schema file to validate against (e.g., templates/output-schema.json)",
    )
    parser.add_argument(
        "--no-trace",
        action="store_true",
        help="Disable Langfuse tracing (bypass the @observe wrapper); guarantees the validator runs.",
    )
    args = parser.parse_args()

    path = args.playbook
    if not Path(path).exists():
        print(f"File not found: {path}")
        sys.exit(1)

    # Only pass a trace id that is a valid 32-char lowercase hex (Langfuse requirement); otherwise
    # None. Placeholder/test ids previously crashed the validator (audit F1).
    import re as _re
    _tid = None if args.no_trace else RunTrace.current_trace_id()
    if not (_tid and _re.fullmatch(r"[0-9a-f]{32}", str(_tid))):
        _tid = None

    if args.no_trace:
        _validate = getattr(_run_validate, "__wrapped__", _run_validate)
        errors, warnings = _validate(path, args.schema)
    else:
        errors, warnings = _run_validate(path, args.schema, langfuse_trace_id=_tid)

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
        print("PASS: All structural checks passed")
        sys.exit(0)


if __name__ == "__main__":
    main()
