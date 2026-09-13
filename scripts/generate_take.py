#!/usr/bin/env python3
"""Dispatch one seeded take to the session's chosen music model.

Usage:
    python scripts/generate_take.py --session studio/sessions/<song-id> --seed 7 \
        [--take-id N] [--model yue2|minimax-music3] [--config configs/provider.toml]

One command for the generate-song skill, so the model -> script mapping lives in
exactly one place (adding a third model is a one-file change here, not a skill
edit). The model is resolved in this order:

  1. --model (explicit override; also used for one-off A/B comparisons)
  2. <session>/model.json, the choice recorded once per session by
     scripts/select_model.py (plan decision Y2)
  3. [models].default from configs/provider.toml

`model_source` in the output says which of the three applied. This script
deliberately does NOT pre-flight the backend's readiness: the generator itself
reports a precise, actionable error (and scripts/select_model.py reports
availability at choice time, which is where the user needs it).

The child's generate/v1 JSON is forwarded verbatim with two additive keys
(`model`, `model_source`), so callers keep parsing one contract.

Exit codes: 0 success; 2 bad inputs/config; otherwise the child's exit code.
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# model engine -> generator script
ENGINE_SCRIPTS = {
    "yue2": "generate_yue2.py",
    "minimax": None,  # resolved from [provider].type below
}
MINIMAX_ENGINE_SCRIPTS = {
    "audiocpp": "generate_audiocpp.py",
    "local": "generate.py",
}

# Which passthrough knobs each generator actually accepts. Checked BEFORE
# dispatch so an unsupported combination fails with a precise message instead of
# an argparse usage error from the child. YuE2 has no duration control at all
# (plan decision Y8); MiniMax Music 3 has no symbolic-planning mode.
PASSTHROUGH_SUPPORT = {
    "generate_yue2.py": frozenset({"cot"}),
    "generate_audiocpp.py": frozenset({"duration_sec"}),
    "generate.py": frozenset({"max_new_tokens"}),
}

# Flags the DISPATCHER owns: they decide routing and the session file contract,
# so an agent may not smuggle them through --extra-arg. Everything else is
# forwarded to the generator (which forwards its own model-native vocabulary on
# to the model CLI) so each model can stay as different as it is — see the
# model-guide skill.
RESERVED_EXTRA_FLAGS = frozenset(
    {
        "--session",
        "--seed",
        "--config",
        "--take-id",
        "--cot",
        "--duration-sec",
        "--max-new-tokens",
    }
)


def emit(payload: dict) -> None:
    print(json.dumps(payload, indent=2))


def fail(message: str, code: int = 2, **extra: object) -> int:
    emit({"schema": "generate/v1", "ok": False, "error": message, **extra})
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True, type=Path)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument(
        "--config", type=Path, default=REPO_ROOT / "configs" / "provider.toml"
    )
    parser.add_argument("--model", default=None, help="Override the session's model choice")
    parser.add_argument("--take-id", type=int, default=None)
    # Passthrough knobs are forwarded only when the caller sets them, so each
    # backend keeps its own vocabulary (audiocpp --duration-sec, yue2 --cot).
    parser.add_argument("--duration-sec", type=int, default=None)
    parser.add_argument("--cot", choices=["full", "melody", "off"], default=None)
    parser.add_argument("--max-new-tokens", type=int, default=None)
    parser.add_argument(
        "--extra-arg",
        action="append",
        default=[],
        metavar="ARGS",
        help="Extra backend-native argument(s) forwarded verbatim to the generator "
        "(repeatable). Each value is shell-split, so --extra-arg \"--quantization fp8\" "
        "works. Flags that carry the session file contract are rejected; see the "
        "model-guide skill for each model's own vocabulary.",
    )
    args = parser.parse_args()

    if not args.config.is_file():
        return fail(f"config not found: {args.config}")
    try:
        cfg = tomllib.loads(args.config.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        return fail(f"config is not valid TOML: {exc}")

    models_cfg = cfg.get("models") or {}
    if not models_cfg:
        return fail("[models] section missing from config")
    available = [str(m) for m in (models_cfg.get("available") or [])]
    default_model = str(models_cfg.get("default", ""))

    session: Path = args.session
    model_source = "flag" if args.model else "default"
    model_id = args.model or default_model

    if args.model is None and session.is_dir():
        choice_path = session / "model.json"
        if choice_path.is_file():
            try:
                choice = json.loads(choice_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return fail(f"{choice_path} is unreadable/corrupt; re-record the model choice")
            recorded = str(choice.get("model", ""))
            if recorded:
                model_id = recorded
                model_source = "session"

    if model_id not in available:
        return fail(
            f"model {model_id!r} is not in [models].available {available}",
            model=model_id,
            model_source=model_source,
        )
    spec = models_cfg.get(model_id) or {}
    engine = str(spec.get("engine", model_id))

    if engine == "minimax":
        provider_engine = str((cfg.get("provider") or {}).get("type", "audiocpp"))
        script_name = MINIMAX_ENGINE_SCRIPTS.get(provider_engine)
        if script_name is None:
            return fail(
                f"[provider].type {provider_engine!r} is not one of "
                f"{sorted(MINIMAX_ENGINE_SCRIPTS)}",
                model=model_id,
                model_source=model_source,
            )
    else:
        script_name = ENGINE_SCRIPTS.get(engine)
        if script_name is None:
            return fail(
                f"no generator is wired for engine {engine!r}",
                model=model_id,
                model_source=model_source,
            )

    script = REPO_ROOT / "scripts" / script_name

    requested: dict[str, object] = {
        "duration_sec": args.duration_sec,
        "cot": args.cot,
        "max_new_tokens": args.max_new_tokens,
    }
    wanted = {name for name, value in requested.items() if value is not None}
    supported = PASSTHROUGH_SUPPORT.get(script_name, frozenset())
    unsupported = sorted(wanted - supported)
    if unsupported:
        flags = ", ".join("--" + name.replace("_", "-") for name in unsupported)
        allowed = sorted("--" + name.replace("_", "-") for name in supported) or ["(none)"]
        return fail(
            f"{flags} is not supported by {script_name} (model {model_id!r}); "
            f"it accepts: {', '.join(allowed)}",
            model=model_id,
            model_source=model_source,
        )

    extra_tokens: list[str] = []
    for raw in args.extra_arg:
        try:
            tokens = shlex.split(raw)
        except ValueError as exc:
            return fail(
                f"--extra-arg {raw!r} is not shell-parseable: {exc}",
                model=model_id,
                model_source=model_source,
            )
        for token in tokens:
            flag = token.split("=", 1)[0]
            if flag in RESERVED_EXTRA_FLAGS:
                return fail(
                    f"--extra-arg may not set {flag}: the dispatcher owns it (it decides "
                    "model routing and the session's take numbering). Use the first-class "
                    "flag, or pass a backend-native option — see the model-guide skill.",
                    model=model_id,
                    model_source=model_source,
                )
        extra_tokens += tokens

    cmd = [
        sys.executable, str(script),
        "--session", str(session),
        "--seed", str(args.seed),
        "--config", str(args.config),
    ]
    if args.take_id is not None:
        cmd += ["--take-id", str(args.take_id)]
    passed: list[str] = []
    if args.duration_sec is not None:
        cmd += ["--duration-sec", str(args.duration_sec)]
        passed.append("duration_sec")
    if args.cot is not None:
        cmd += ["--cot", args.cot]
        passed.append("cot")
    if args.max_new_tokens is not None:
        cmd += ["--max-new-tokens", str(args.max_new_tokens)]
        passed.append("max_new_tokens")
    # Forward each original value behind --extra-arg: the generators take the
    # model-native vocabulary through that flag, not as bare arguments. Use the
    # attached KEY=VALUE form so a value beginning with "--" (e.g. "--quiet") is
    # not mistaken for an option by the child's argparse.
    for raw in args.extra_arg:
        cmd.append(f"--extra-arg={raw}")

    proc = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
    )

    try:
        child = json.loads(proc.stdout)
    except json.JSONDecodeError:
        # Surface the child's own diagnostics rather than an empty parse error.
        sys.stderr.write(
            f"[generate_take] {script_name} rc={proc.returncode} did not print JSON\n"
            f"--- stdout tail ---\n{chr(10).join(proc.stdout.splitlines()[-20:])}\n"
            f"--- stderr tail ---\n{chr(10).join(proc.stderr.splitlines()[-20:])}\n"
        )
        return fail(
            f"{script_name} did not emit a generate/v1 JSON document (rc={proc.returncode})",
            code=proc.returncode or 8,
            model=model_id,
            model_source=model_source,
            script=script_name,
        )

    if not isinstance(child, dict):
        return fail(f"{script_name} emitted a non-object JSON document", code=8)

    out = {
        **child,
        "model": model_id,
        "model_source": model_source,
        "generator": script_name,
    }
    if passed:
        out["passthrough"] = passed
    if extra_tokens:
        out["extra_args"] = extra_tokens
    emit(out)
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
