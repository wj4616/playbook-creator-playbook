"""Smoke tests for the public distribution: the shipped meta-playbook and template are valid."""
import json
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "templates" / "output-schema.json").read_text())
META = ROOT / "playbook-creator-playbook.json"
TEMPLATE = ROOT / "templates" / "output-template.json"


def test_meta_playbook_matches_output_schema():
    data = json.loads(META.read_text())
    errors = list(jsonschema.Draft7Validator(SCHEMA).iter_errors(data))
    assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors)


def test_meta_playbook_has_16_phases_and_v7_plus():
    data = json.loads(META.read_text())
    assert data["version"] >= 7
    assert len(data["phase_summary"]) == 16
    assert len(data["checklists"]) == 16


def test_template_is_schema_valid_skeleton():
    data = json.loads(TEMPLATE.read_text())
    errors = list(jsonschema.Draft7Validator(SCHEMA).iter_errors(data))
    assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors)


def test_provider_tiers_present():
    d = json.loads(META.read_text())["defaults"]
    assert d["provider"] in d["providers"]
    for prov in ("anthropic", "openai_codex", "generic"):
        assert {"frontier", "high", "fast"} <= set(d["providers"][prov])


def test_structural_validator_runs_standalone():
    r = subprocess.run(
        [sys.executable, "scripts/validate_playbook.py", "--no-trace",
         "playbook-creator-playbook.json", "--schema", "templates/output-schema.json"],
        cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_semantic_validator_runs_standalone():
    r = subprocess.run(
        [sys.executable, "scripts/validate_semantic.py", "playbook-creator-playbook.json"],
        cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout
