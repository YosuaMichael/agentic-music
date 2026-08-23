#!/usr/bin/env python3
"""Control and inspect the local SGLang-Omni music server running in WSL.

Usage:
    python scripts/serve.py run      # foreground; wrap in a persistent bg job
    python scripts/serve.py status
    python scripts/serve.py stop

Why `run` instead of a self-daemonizing `start`: the Ubuntu-24.04 WSL image
runs systemd, and session-scoped processes get SIGKILLed when the launching
console disconnects — a daemonized server dies silently with its buffered
logs. Running the server in the foreground of a long-lived background job
(harness job, tmux pane, etc.) keeps it alive AND streams its logs.

Stdlib-only (tomllib + subprocess + urllib); safe to run from the Windows host
or any Linux shell. The server itself always runs inside distro Ubuntu-24.04
with weights at configs/provider.toml -> [local].weights_path_wsl.

JSON contract (stdout):

    serve/v1
    {
      "schema": "serve/v1",
      "action": "run|status|stop",
      "ok": true,
      "server": {"running": true, "pid": 1234|null, "port": 8000,
                  "healthy": true|false, "http_status": 200|null},
      "vram_used_mib": 8123|null,
      "detail": "human-readable note"
    }

`run` streams raw server output to stdout/stderr and exits only when the
server exits; it does NOT emit the JSON contract.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

WSL_DISTRO = "Ubuntu-24.04"
VENV_BIN = "/root/agentic-music-venv/bin"
LOG_PATH = "/root/agentic-music-server.log"
PID_PATH = "/root/agentic-music-server.pid"


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def windows_repo_to_wsl(path: Path) -> str:
    """Map a repo-relative/absolute Windows path to its /mnt/<drive> WSL path."""
    absolute = path if path.is_absolute() else repo_root() / path
    resolved = absolute.resolve()
    drive = resolved.drive.rstrip(":").lower()
    tail = resolved.as_posix().split(":", 1)[-1]  # drop "C:" -> "/Users/..."
    return f"/mnt/{drive}{tail}"


def load_local_config() -> tuple[str, int, str, list[str]]:
    cfg = tomllib.loads((repo_root() / "configs" / "provider.toml").read_text())
    local = cfg["local"]
    extra = [str(a) for a in local.get("extra_serve_args", [])]
    pipeline_cfg = local.get("pipeline_config")
    if "--config" not in extra and pipeline_cfg:
        # Resolve repo-relative config paths to their /mnt/<drive> location so
        # the committed provider.toml stays machine-independent.
        wsl_path = (
            str(pipeline_cfg)
            if str(pipeline_cfg).startswith("/")
            else windows_repo_to_wsl(Path(str(pipeline_cfg)))
        )
        extra = ["--config", wsl_path, *extra]
    return local["host"], int(local["port"]), local["weights_path_wsl"], extra


def wsl_bash(script: str) -> str | None:
    """Run a bash snippet inside WSL; return stdout or None on failure."""
    try:
        proc = subprocess.run(
            ["wsl.exe", "-d", WSL_DISTRO, "-u", "root", "--", "bash", "-c", script],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def probe_http(host: str, port: int, path: str) -> int | None:
    for candidate in (f"http://{host}:{port}{path}",):
        try:
            with urllib.request.urlopen(candidate, timeout=10) as resp:
                return resp.status
        except urllib.error.HTTPError as exc:
            return exc.code
        except (urllib.error.URLError, OSError):
            continue
    return None


def gather_status(host: str, port: int) -> dict[str, object]:
    raw = wsl_bash(
        "pgrep -f sgl-omni\\ serve | head -1 | sed 's/^/PID=/' ; "
        "nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits "
        "| head -1 | sed 's/^/VRAM=/'"
    )
    parsed: dict[str, object] = {"pid": None, "running": False, "vram_used_mib": None}
    if raw:
        for line in raw.splitlines():
            key, _, value = line.partition("=")
            if key == "PID" and value.strip().isdigit():
                parsed["pid"] = int(value)
                parsed["running"] = True
            elif key == "VRAM" and value.strip().isdigit():
                parsed["vram_used_mib"] = int(value.strip())
    http = probe_http(host, port, "/health")
    if http is None:
        http = probe_http(host, port, "/v1/models")
    parsed["http_status"] = http
    parsed["healthy"] = bool(parsed["running"]) and http is not None
    return parsed


def emit(action: str, ok: bool, detail: str, **extra: object) -> int:
    print(
        json.dumps(
            {
                "schema": "serve/v1",
                "action": action,
                "ok": ok,
                **({"server": extra["server"]} if "server" in extra else {}),
                "vram_used_mib": extra.get("vram_used_mib"),
                "detail": detail,
            },
            indent=2,
        )
    )
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["run", "stop", "status"])
    args = parser.parse_args()

    host, port, weights, extra_args = load_local_config()

    if args.action == "status":
        state = gather_status(host, port)
        detail = "healthy" if state["healthy"] else "not healthy"
        return emit("status", True, detail, server=state)

    if args.action == "run":
        cmd = [
            "wsl.exe", "-d", WSL_DISTRO, "-u", "root", "--",
            f"{VENV_BIN}/sgl-omni", "serve",
            "--model-path", weights,
            "--port", str(port),
            *extra_args,
        ]
        print(f"[serve.py] launching: {' '.join(cmd)}", file=sys.stderr, flush=True)
        proc = subprocess.run(cmd, check=False)
        print(
            json.dumps(
                {
                    "schema": "serve/v1",
                    "action": "run",
                    "ok": proc.returncode == 0,
                    "server": {"running": False, "pid": None, "port": port},
                    "vram_used_mib": None,
                    "detail": f"server exited with code {proc.returncode}",
                }
            )
        )
        return proc.returncode

    # stop: pidfile is best-effort; also sweep any stray server processes
    wsl_bash(
        "pkill -f sgl-omni\\ serve ; sleep 2 ; pkill -9 -f sgl-omni\\ serve ; "
        f"rm -f {PID_PATH} ; echo stopped"
    )
    state = gather_status(host, port)
    detail = "stopped" if not state["running"] else "still running after stop attempt"
    return emit("stop", not state["running"], detail)


if __name__ == "__main__":
    sys.exit(main())
