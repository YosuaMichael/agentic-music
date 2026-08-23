#!/usr/bin/env python3
"""Deterministic hardware/tooling audit for agentic-music.

Runs on the Windows host or inside WSL/Linux. Stdout carries exactly one JSON
document; human-readable progress goes to stderr. Exit code 0 unless an
unrecoverable audit error occurred.

JSON contract (stdout):

    hardware_audit/v1
    {
      "schema": "hardware_audit/v1",
      "time_utc": "ISO-8601 timestamp",
      "platform": {
        "system": "Windows|Linux",
        "release": "...",
        "is_wsl": false,
        "wsl_distro": null | "Ubuntu-24.04"   // set when run inside WSL
      },
      "gpus": [
        {"index": 0, "name": "...", "memory_total_mib": 24564, "driver": "..."}
      ],
      "disks": [ {"mount": "C:\\" | "/", "free_gb": 581.3} ],
      "tools": { "python": "...", "uv": "...", "git": "...",
                 "ffmpeg": "...|null", "curl": "..." },
      "notes": ["human-readable advisory strings"],
      "verdict": {"single_gpu_vram_ok": true|false|null}
    }
"""

from __future__ import annotations

import json
import platform
import shutil
import string
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

SINGLE_GPU_MIN_VRAM_MIB = 23000  # RTX 4090-class bar from decision D1


def _run(cmd: list[str]) -> str | None:
    """Return stdout of a command, or None if it cannot run."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def detect_gpus() -> list[dict[str, object]]:
    out = _run(
        [
            "nvidia-smi",
            "--query-gpu=index,name,memory.total,driver_version",
            "--format=csv,noheader,nounits",
        ]
    )
    gpus: list[dict[str, object]] = []
    if not out:
        return gpus
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 4:
            continue
        try:
            gpus.append(
                {
                    "index": int(parts[0]),
                    "name": parts[1],
                    "memory_total_mib": int(float(parts[2])),
                    "driver": parts[3],
                }
            )
        except ValueError:
            continue
    return gpus


def detect_disks() -> list[dict[str, object]]:
    disks: list[dict[str, object]] = []
    system = platform.system()
    if system == "Windows":
        for letter in string.ascii_uppercase:
            root = f"{letter}:\\"
            if Path(root).exists():
                usage = shutil.disk_usage(root)
                disks.append({"mount": root, "free_gb": round(usage.free / 1024**3, 1)})
    else:
        for mount in ("/", "/mnt/c"):
            if Path(mount).exists():
                usage = shutil.disk_usage(mount)
                disks.append({"mount": mount, "free_gb": round(usage.free / 1024**3, 1)})
    return disks


def detect_tools() -> dict[str, str | None]:
    tools = {"python": None, "uv": None, "git": None, "ffmpeg": None, "curl": None}
    py_out = _run([sys.executable, "--version"])
    if py_out:
        tools["python"] = py_out
    else:
        tools["python"] = _run(["python3", "--version"]) or _run(["python", "--version"])
    for name in ("uv", "git", "ffmpeg", "curl"):
        found = shutil.which(name)
        if found:
            ver_cmd = [name, "--version"] if name not in ("ffmpeg",) else [name, "-version"]
            first_line = (_run(ver_cmd) or "").splitlines()
            tools[name] = first_line[0] if first_line else found
    return tools


def detect_wsl() -> tuple[bool, str | None]:
    version_file = Path("/proc/version")
    if version_file.exists():
        content = version_file.read_text(errors="ignore")
        if "microsoft" in content.lower():
            env = (
                platform.freedesktop_os_release()
                if hasattr(platform, "freedesktop_os_release")
                else {}
            )
            return True, env.get("ID", None)
    return False, None


def wsl_distros_windows() -> list[str]:
    out = _run(["wsl.exe", "--list", "--quiet"])
    if not out:
        return []
    cleaned = out.replace("\x00", "")
    return [d.strip() for d in cleaned.splitlines() if d.strip()]


def main() -> int:
    is_wsl, distro = detect_wsl()
    gpus = detect_gpus()
    total_vram = sum(int(g["memory_total_mib"]) for g in gpus)

    notes: list[str] = []
    verdict: bool | None = None
    if len(gpus) == 0:
        notes.append("No NVIDIA GPU detected via nvidia-smi.")
        verdict = False
    elif len(gpus) == 1 and int(gpus[0]["memory_total_mib"]) >= SINGLE_GPU_MIN_VRAM_MIB:
        notes.append(
            f"{len(gpus)} GPU with {int(gpus[0]['memory_total_mib'])} MiB meets the "
            f">{SINGLE_GPU_MIN_VRAM_MIB} MiB single-GPU bar (decision D1)."
        )
        verdict = True
    elif total_vram >= SINGLE_GPU_MIN_VRAM_MIB * 2:
        notes.append("Multi-GPU layout matches upstream's documented two-GPU serving path.")
        verdict = True
    else:
        notes.append("VRAM below documented requirements; Phase 0 spike will decide.")

    report = {
        "schema": "hardware_audit/v1",
        "time_utc": datetime.now(UTC).isoformat(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "is_wsl": is_wsl,
            "wsl_distro": distro,
        },
        "gpus": gpus,
        "disks": detect_disks(),
        "tools": detect_tools(),
        "notes": notes,
        "verdict": {"single_gpu_vram_ok": verdict},
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
