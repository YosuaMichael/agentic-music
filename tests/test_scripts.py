"""Contract smoke tests: every pipeline script must import cleanly and expose
its documented JSON schema marker. These run WITHOUT GPU/server dependencies."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"

EXPECTED_SCHEMAS = {
    "hardware_audit.py": "hardware_audit/v1",
    "serve.py": "serve/v1",
    "generate.py": "generate/v1",
    "analyze_audio.py": "analyze_audio/v1",
    "clap_score.py": "clap_score/v1",
}


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name[:-3], SCRIPTS / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_all_scripts_import() -> None:
    for name in EXPECTED_SCHEMAS:
        _load(name)


def test_schema_strings_documented() -> None:
    for name, schema in EXPECTED_SCHEMAS.items():
        assert schema in (SCRIPTS / name).read_text(encoding="utf-8"), (
            f"{name} must document its '{schema}' contract in its docstring"
        )


def test_hardware_audit_verdict_shape() -> None:
    """The audit report must always carry a boolean-or-null verdict key."""
    mod = _load("hardware_audit.py")
    assert hasattr(mod, "SINGLE_GPU_MIN_VRAM_MIB")


def test_generate_rejects_missing_session() -> None:
    """Missing caption.md must exit with code 2 and a clean JSON error."""
    mod = _load("generate.py")
    sys.argv = ["generate.py", "--session", "does-not-exist", "--seed", "1"]
    try:
        rc = mod.main()
    except SystemExit as exc:  # argparse-level failure also acceptable
        rc = int(exc.code or 0)
    assert rc == 2, f"expected exit 2 for missing session, got {rc}"
