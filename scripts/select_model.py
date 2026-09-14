#!/usr/bin/env python3
"""Choose which music model a song session uses — asked ONCE per session.

Usage:
    python scripts/select_model.py --list
    python scripts/select_model.py --session studio/sessions/<song-id>
    python scripts/select_model.py --session studio/sessions/<song-id> --model yue2
    python scripts/select_model.py --session studio/sessions/<song-id> \
        --model minimax-music3 --force

Why this script owns the choice: the model must be picked at the START of a song
and then never asked again (plan 2026-09-13-yue2-default-model.md, decision Y2).
The answer is session state, not global config, so

  * creation agents in studio/ never have to edit configs/,
  * a session stays faithful to whatever actually produced its takes, and
  * re-rendering an old session with the other model is a per-session decision.

Read/write model of <session>/model.json (model_choice/v1):
    {"schema": "model_choice/v1", "model": "yue2", "source": "user|default",
     "chosen_utc": "ISO-8601", "recorded_by": "scripts/select_model.py"}

`needs_choice` is the ask gate: when it is true the calling skill asks the user
ONCE (proposing `default`), then calls this script again with --model. Once the
file exists the question is never repeated.

This script also reports per-model AVAILABILITY (is the runtime installed? are
the weights present?) so the question can be honest about what this machine can
actually run today. Availability of `ready: null` means "not determined" — the
MiniMax SGLang server path is checked with scripts/serve.py status instead.

JSON contract (stdout) — select_model/v1:
    {
      "schema": "select_model/v1",
      "ok": true,
      "session": "studio/sessions/<id>"|null,
      "default": "yue2",
      "available": [
        {"id": "yue2", "label": "...", "engine": "yue2",
         "prompt_artifact": "style.txt", "supports_instrumental": false,
         "weights_license": "CC BY-NC 4.0 (non-commercial)",
         "commercial_use": false, "ready": true|false|null,
         "details": {"runtime": "wsl", "venv_present": true,
                     "weights_present": true, "probe_error": null}}
      ],
      "chosen": {"model": "yue2", "source": "user|default", "recorded": true,
                 "chosen_utc": "...", "known": true}|null,
      "needs_choice": true|false|null,
      "error": null
    }

Exit codes: 0 success; 2 bad inputs/config or an unusable recorded choice;
8 runtime probe failure (only when a probe was explicitly required).

Stdlib-only. Runs on the Windows host or inside WSL/Linux: with
[yue2].runtime = "wsl" on a Linux host the WSL layer is skipped and the runtime
is treated as native (that is what running inside WSL means).
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHOICE_FILENAME = "model.json"
CHOICE_SCHEMA = "model_choice/v1"


# --------------------------------------------------------------------------- #
# Runtime plumbing: run commands either directly (Linux) or through WSL2.
# --------------------------------------------------------------------------- #


@dataclass
class RunResult:
    rc: int
    out: str
    err: str

    @property
    def ok(self) -> bool:
        return self.rc == 0


class Runtime:
    """Executes commands inside the configured YuE2 runtime."""

    def __init__(self, yue2_cfg: dict, repo_root: Path = REPO_ROOT) -> None:
        self.repo_root = repo_root
        configured = str(yue2_cfg.get("runtime", "wsl"))
        # A "wsl" config executed from inside Linux already IS the runtime.
        self.mode = "native" if (configured == "wsl" and platform.system() != "Windows") else configured
        self.distro = str(yue2_cfg.get("wsl_distro", "Ubuntu-24.04"))
        self.user = str(yue2_cfg.get("wsl_user", "root"))
        self._home: str | None = None

    def _prepare(self, argv: list[str]) -> list[str]:
        if self.mode == "wsl":
            return ["wsl.exe", "-d", self.distro, "-u", self.user, "--", *argv]
        return argv

    def run(self, argv: list[str], timeout: int = 60) -> RunResult:
        try:
            proc = subprocess.run(
                self._prepare(argv),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return RunResult(124, "", f"timed out after {timeout}s")
        except OSError as exc:
            return RunResult(
                127, "", f"cannot launch {argv[0]!r}: {exc} (is WSL installed?)"
            )
        out = (proc.stdout or "").replace("\x00", "")
        err = (proc.stderr or "").replace("\x00", "")
        return RunResult(proc.returncode, out, err)

    def bash(self, script: str, timeout: int = 60) -> RunResult:
        return self.run(["bash", "-c", script], timeout=timeout)

    def home(self) -> str | None:
        """Resolve $HOME inside the runtime (cached)."""
        if self._home is None:
            if self.mode == "native":
                self._home = os.path.expanduser("~")
            else:
                res = self.bash('printf %s "$HOME"')
                self._home = res.out.strip() if res.rc == 0 and res.out.strip() else None
        return self._home

    def path(self, configured: str) -> str | None:
        """Map a host path into the runtime: expand ~, map repo-relative and
        drive-absolute Windows paths onto the WSL /mnt/<drive> mount."""
        if not configured:
            return None
        if configured.startswith("~"):
            home = self.home()
            if home is None:
                return None
            return home + configured[1:]
        if configured.startswith("/"):  # POSIX absolute: already runtime-valid
            return configured
        candidate = Path(configured)
        if candidate.is_absolute():
            absolute = candidate
        else:
            absolute = (self.repo_root / configured).resolve()
        if self.mode == "native":
            return str(absolute)
        drive = absolute.drive.rstrip(":").lower()
        if not drive:
            return None
        tail = absolute.as_posix().split(":", 1)[-1]
        return f"/mnt/{drive}{tail}"


def probe_paths(rt: Runtime, checks: list[tuple[str, str]], timeout: int = 60) -> dict[str, bool]:
    """Evaluate `test -d`/`test -x`-style conditions in ONE runtime round-trip."""
    if not checks:
        return {}
    script = " ; ".join(
        f'if {cond}; then echo "OK:{i}"; else echo "MISS:{i}"; fi'
        for i, (_name, cond) in enumerate(checks)
    )
    res = rt.bash(script, timeout=timeout)
    results = {name: False for name, _cond in checks}
    if res.rc != 0 and not res.out.strip():
        return results
    for line in res.out.splitlines():
        key, _, value = line.strip().partition(":")
        if key in ("OK", "MISS") and value.isdigit():
            index = int(value)
            if 0 <= index < len(checks):
                results[checks[index][0]] = key == "OK"
    return results


# --------------------------------------------------------------------------- #
# Availability probes
# --------------------------------------------------------------------------- #


def probe_yue2(yue2: dict, repo_root: Path) -> dict[str, object]:
    rt = Runtime(yue2, repo_root)
    details: dict[str, object] = {
        "runtime": rt.mode,
        "venv_dir": str(yue2.get("venv_dir", "")),
        "weights_dir": str(yue2.get("weights_dir", "")),
        "venv_present": False,
        "weights_present": False,
        "probe_error": None,
    }
    if rt.mode not in ("wsl", "native"):
        details["probe_error"] = f"unknown [yue2].runtime {rt.mode!r}"
        return {"ready": False, "details": details}

    venv = rt.path(str(yue2.get("venv_dir", "")))
    if venv is None:
        details["probe_error"] = (
            "runtime unreachable: cannot resolve $HOME"
            + (" (is WSL installed and running?)" if rt.mode == "wsl" else "")
        )
        return {"ready": None, "details": details}
    details["venv_dir_resolved"] = venv

    model_override = str(yue2.get("model", "") or "").strip()
    checks: list[tuple[str, str]] = [("venv_present", f'test -x "{venv}/bin/yue2"')]

    if model_override:
        # A local model directory replaces the HF cache as the weight source.
        local = rt.path(model_override)
        details["weights_source"] = "local_dir"
        details["weights_dir_resolved"] = local
        if local is None:
            details["probe_error"] = f"cannot resolve [yue2].model {model_override!r}"
            return {"ready": None, "details": details}
        checks.append(("weights_present", f'test -d "{local}"'))
    else:
        weights = rt.path(str(yue2.get("weights_dir", "")))
        details["weights_source"] = "hf_cache"
        details["weights_dir_resolved"] = weights
        if weights is None:
            details["probe_error"] = f"cannot resolve [yue2].weights_dir in runtime {rt.mode!r}"
            return {"ready": None, "details": details}
        # huggingface_hub cache layout: <HF_HOME>/hub/models--<org>--<name>/
        for repo in yue2.get("hf_models", []) or []:
            slug = str(repo).replace("/", "--")
            checks.append(("weights_present", f'test -d "{weights}/hub/models--{slug}"'))

    found = probe_paths(rt, checks)
    details["venv_present"] = bool(found.get("venv_present"))
    details["weights_present"] = bool(found.get("weights_present"))
    ready = bool(details["venv_present"]) and bool(details["weights_present"])
    if not ready:
        details["remedy"] = "python scripts/setup_yue2.py"
    return {"ready": ready, "details": details}


def probe_minimax(provider: dict, repo_root: Path, minimax: dict) -> dict[str, object]:
    engine = str(provider.get("type", "audiocpp"))
    details: dict[str, object] = {"engine": engine, "probe_error": None}
    if engine == "audiocpp":
        cfg = provider.get("_audiocpp") or {}
        cli = repo_root / str(cfg.get("cli_path", ""))
        model_dir = repo_root / str(cfg.get("model_dir", ""))
        details["cli"] = str(cli)
        details["model_dir"] = str(model_dir)
        details["cli_present"] = cli.is_file()
        details["model_dir_present"] = model_dir.is_dir()
        ready = bool(details["cli_present"]) and bool(details["model_dir_present"])
        if not ready:
            details["remedy"] = "python scripts/setup_audiocpp.py"
        return {"ready": ready, "details": details}

    # SGLang-Omni server path: health lives behind scripts/serve.py status, not here.
    details["engine"] = "local"
    details["note"] = "server path - verify with: python scripts/serve.py status"
    details["weights_path_wsl"] = str(minimax.get("weights_path_wsl", ""))
    return {"ready": None, "details": details}


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #


def build_registry(cfg: dict, repo_root: Path) -> list[dict[str, object]]:
    models_cfg = cfg.get("models") or {}
    order = [str(m) for m in (models_cfg.get("available") or [])]
    entries: list[dict[str, object]] = []
    for model_id in order:
        spec = models_cfg.get(model_id) or {}
        engine = str(spec.get("engine", model_id))
        entry: dict[str, object] = {
            "id": model_id,
            "label": str(spec.get("label", model_id)),
            "engine": engine,
            "prompt_artifact": spec.get("prompt_artifact"),
            "supports_instrumental": spec.get("supports_instrumental"),
            "weights_license": spec.get("weights_license"),
            "commercial_use": spec.get("commercial_use"),
        }
        if engine == "yue2":
            probe = probe_yue2(cfg.get("yue2") or {}, repo_root)
        elif engine == "minimax":
            probe = probe_minimax(cfg.get("provider") or {}, repo_root, cfg.get("local") or {})
        else:
            probe = {"ready": None, "details": {"probe_error": f"unknown engine {engine!r}"}}
        entry["ready"] = probe["ready"]
        entry["details"] = probe["details"]
        entries.append(entry)
    return entries


# --------------------------------------------------------------------------- #
# Session choice state
# --------------------------------------------------------------------------- #


def read_choice(session: Path) -> dict[str, object] | None:
    path = session / CHOICE_FILENAME
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_choice(session: Path, model_id: str, source: str) -> dict[str, object]:
    record = {
        "schema": CHOICE_SCHEMA,
        "model": model_id,
        "source": source,
        "chosen_utc": datetime.now(UTC).isoformat(),
        "recorded_by": "scripts/select_model.py",
    }
    (session / CHOICE_FILENAME).write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8"
    )
    return record


def emit(payload: dict, code: int = 0) -> int:
    print(json.dumps({"schema": "select_model/v1", **payload}, indent=2))
    return code


def fail(message: str, **extra: object) -> int:
    return emit(
        {
            "ok": False,
            "session": extra.get("session"),
            "default": extra.get("default"),
            "available": extra.get("available", []),
            "chosen": extra.get("chosen"),
            "needs_choice": extra.get("needs_choice"),
            "error": message,
        },
        2,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=Path, default=None, help="Song session directory")
    parser.add_argument("--model", default=None, help="Record this model id as the choice")
    parser.add_argument(
        "--list", action="store_true", help="Report the registry + availability only"
    )
    parser.add_argument(
        "--force", action="store_true", help="Overwrite an existing recorded choice"
    )
    parser.add_argument(
        "--config", type=Path, default=REPO_ROOT / "configs" / "provider.toml"
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
        return fail("[models] section missing from config (see plans/2026-09-13-yue2-default-model.md)")
    default_model = str(models_cfg.get("default", ""))
    ids = [str(m) for m in (models_cfg.get("available") or [])]
    if not ids:
        return fail("[models].available is empty")
    if default_model not in ids:
        return fail(f"[models].default {default_model!r} is not in [models].available {ids}")

    # Attach the audiocpp section for the MiniMax engine probe (keeps the probe
    # signature self-contained without another config read).
    provider = dict(cfg.get("provider") or {})
    provider["_audiocpp"] = cfg.get("audiocpp") or {}
    probe_cfg = {**cfg, "provider": provider}

    available = build_registry(probe_cfg, args.config.resolve().parent.parent)

    if args.model is not None and args.model not in ids:
        return fail(
            f"unknown model {args.model!r}; available: {ids}",
            default=default_model,
            available=available,
        )
    if args.model is not None and args.session is None:
        return fail("--model requires --session (a model choice is session state)", available=available)
    if args.session is None and not args.list:
        return fail("provide --session, or --list to inspect the registry without a session")

    session: Path | None = args.session
    chosen: dict[str, object] | None = None
    needs_choice: bool | None = None

    if session is not None:
        session = session.resolve()
        if not session.is_dir():
            return fail(
                f"session directory does not exist: {session} "
                "(compose-brief creates it at the start of a song)",
                default=default_model,
                available=available,
            )

        existing: dict[str, object] | None
        try:
            existing = read_choice(session)
        except (json.JSONDecodeError, OSError) as exc:
            return fail(
                f"{session / CHOICE_FILENAME} is unreadable/corrupt: {exc} "
                "(delete it or re-record with --model ... --force)",
                session=str(session),
                default=default_model,
                available=available,
            )
        if existing is not None and str(existing.get("model", "")) not in ids:
            return fail(
                f"recorded model {existing.get('model')!r} is not in [models].available {ids} "
                "(re-record with --model <id> --force)",
                session=str(session),
                default=default_model,
                available=available,
            )

        if args.model is not None:
            if existing is not None and not args.force:
                # Refuse to silently re-decide a session. The already-recorded
                # choice is still returned so the caller can carry on with it.
                chosen = {
                    "model": str(existing.get("model")),
                    "source": str(existing.get("source", "user")),
                    "recorded": True,
                    "chosen_utc": existing.get("chosen_utc"),
                    "known": True,
                }
                return emit(
                    {
                        "ok": False,
                        "session": str(session),
                        "default": default_model,
                        "available": available,
                        "chosen": chosen,
                        "needs_choice": False,
                        "error": f"a choice is already recorded ({chosen['model']}); "
                        "pass --force to override",
                    },
                    2,
                )
            record = write_choice(session, args.model, "user")
            chosen = {
                "model": args.model,
                "source": "user",
                "recorded": True,
                "chosen_utc": record["chosen_utc"],
                "known": True,
            }
            needs_choice = False
        elif existing is not None:
            chosen = {
                "model": str(existing.get("model")),
                "source": str(existing.get("source", "user")),
                "recorded": True,
                "chosen_utc": existing.get("chosen_utc"),
                "known": True,
            }
            needs_choice = False  # asked once already: never ask again
        else:
            chosen = {
                "model": default_model,
                "source": "default",
                "recorded": False,
                "chosen_utc": None,
                "known": True,
            }
            needs_choice = True

    return emit(
        {
            "ok": True,
            "session": str(session) if session is not None else None,
            "default": default_model,
            "available": available,
            "chosen": chosen,
            "needs_choice": needs_choice,
            "error": None,
        }
    )


if __name__ == "__main__":
    sys.exit(main())
