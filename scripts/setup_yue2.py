#!/usr/bin/env python3
"""Set up the YuE2 music-model runtime (venv, upstream install, weights).

Usage:
    python scripts/setup_yue2.py [--config configs/provider.toml]
                                [--install-source checkout|wheel]
                                [--skip-weights] [--force]

Long-running and idempotent: it is run as a managed background job by the
env-setup skill, and re-running it only does the work that is still missing.
YuE2 is Linux-only upstream (no Windows instructions, `torch==2.10.0` pinned),
so on Windows this drives the WSL2 distro from [yue2].wsl_distro; on Linux it
runs natively. See plans/2026-09-13-yue2-default-model.md (decisions Y4/Y6).

Steps, each gated:
  1. host hardware audit (scripts/hardware_audit.py) -> GPU VRAM >= min_vram_gb
  2. runtime reachable (distro exists / bash works) + python present
  3. pinned upstream checkout present in src_dir (scripts/fetch_upstream.sh)
  4. venv created in venv_dir
  5. YuE2 installed into it (checkout = Apache-2.0 source, upstream's documented
     quick start; wheel = the v0.1.6 release archive, whose bundled licence puts
     first-party code under CC BY-NC 4.0 too - a fallback, not the default)
  6. model weights fetched into weights_dir (~7.8 GB, HF_HOME)
  7. `yue2 doctor` gate + CUDA visibility inside the runtime

WEIGHTS LICENCE: m-a-p/YuE2-3B and YuE2-Vae are CC BY-NC 4.0 (NON-COMMERCIAL).

JSON contract (stdout) — setup_yue2/v1:
    {"schema": "setup_yue2/v1", "ok": true, "runtime": "wsl|native",
     "distro": "Ubuntu-24.04"|null, "actions": [...], "skipped": [...],
     "warnings": [...], "installed_version": "0.1.6"|null,
     "venv_dir": "<resolved>", "weights_dir": "<resolved>",
     "weights_present": {"m-a-p/YuE2-3B": true, "m-a-p/YuE2-Vae": true},
     "cuda_visible": true|null, "doctor_ok": true|null, "doctor_tail": "...",
     "ready_for_generation": true, "error": null}

`ok` means the install steps succeeded; `ready_for_generation` additionally
requires the weights and a CUDA device visible inside the runtime.

Exit codes: 0 success; 2 bad inputs/config/gate failure; 8 install or download
failure.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TIMEOUT_S = 7200


def tail(text: str, lines: int = 25) -> str:
    return "\n".join(text.splitlines()[-lines:])


# --------------------------------------------------------------------------- #
# Runtime plumbing (WSL2 on Windows, native on Linux)
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
            return RunResult(127, "", f"cannot launch {argv[0]!r}: {exc}")
        return RunResult(
            proc.returncode,
            (proc.stdout or "").replace("\x00", ""),
            (proc.stderr or "").replace("\x00", ""),
        )

    def bash(self, script: str, timeout: int = 60) -> RunResult:
        return self.run(["bash", "-c", script], timeout=timeout)

    def home(self) -> str | None:
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
        tail_path = absolute.as_posix().split(":", 1)[-1]
        return f"/mnt/{drive}{tail_path}"


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #


@dataclass
class Report:
    runtime: str
    distro: str | None
    actions: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    installed_version: str | None = None
    venv_dir: str | None = None
    weights_dir: str | None = None
    weights_present: dict[str, bool] = field(default_factory=dict)
    cuda_visible: bool | None = None
    doctor_ok: bool | None = None
    doctor_tail: str = ""
    error: str | None = None

    def emit(self, ok: bool, code: int) -> int:
        payload = {
            "schema": "setup_yue2/v1",
            "ok": ok,
            "runtime": self.runtime,
            "distro": self.distro,
            "actions": self.actions,
            "skipped": self.skipped,
            "warnings": self.warnings,
            "installed_version": self.installed_version,
            "venv_dir": self.venv_dir,
            "weights_dir": self.weights_dir,
            "weights_present": self.weights_present,
            "cuda_visible": self.cuda_visible,
            "doctor_ok": self.doctor_ok,
            "doctor_tail": self.doctor_tail,
            "ready_for_generation": bool(
                ok
                and self.venv_dir
                and self.weights_present
                and all(self.weights_present.values())
                and self.cuda_visible
                and self.doctor_ok
            ),
            "error": self.error,
        }
        print(json.dumps(payload, indent=2))
        return code


def installed_yue2_version(rt: Runtime, venv: str) -> str | None:
    res = rt.run(
        [f"{venv}/bin/python", "-m", "pip", "list", "--format=json", "--disable-pip-version-check"],
        timeout=180,
    )
    if not res.ok:
        return None
    try:
        entries = json.loads(res.out)
    except json.JSONDecodeError:
        return None
    for entry in entries:
        name = str(entry.get("name", "")).lower()
        if "yue2" in name:
            return str(entry.get("version"))
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=REPO_ROOT / "configs" / "provider.toml"
    )
    parser.add_argument(
        "--install-source",
        choices=["checkout", "wheel"],
        default=None,
        help="Override [yue2].install_source for this run",
    )
    parser.add_argument(
        "--skip-weights", action="store_true", help="Install the runtime only"
    )
    parser.add_argument(
        "--force", action="store_true", help="Reinstall the package / re-fetch weights"
    )
    args = parser.parse_args()

    # One consistent report shape on every exit path, including early refusals.
    report = Report(runtime="unknown", distro=None)

    if not args.config.is_file():
        report.error = f"config not found: {args.config}"
        return report.emit(False, 2)

    try:
        cfg = tomllib.loads(args.config.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        report.error = f"config is not valid TOML: {exc}"
        return report.emit(False, 2)

    y = cfg.get("yue2")
    if not y:
        report.error = "[yue2] section missing from config"
        return report.emit(False, 2)

    repo_root = args.config.resolve().parent.parent
    rt = Runtime(y, repo_root)
    report.runtime = rt.mode
    report.distro = rt.distro if rt.mode == "wsl" else None

    install_source = args.install_source or str(y.get("install_source", "checkout"))

    # --- Step 1: host hardware gate -----------------------------------------
    audit_proc = subprocess.run(
        [sys.executable, str(repo_root / "scripts" / "hardware_audit.py")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        check=False,
    )
    try:
        audit = json.loads(audit_proc.stdout)
    except json.JSONDecodeError:
        report.error = "hardware_audit.py did not return JSON; run it directly"
        return report.emit(False, 2)

    gpus = audit.get("gpus") or []
    # Compare in DECIMAL GB, matching how VRAM capacity is advertised: an RTX 4090
    # reports 24564 MiB, not 24576, so a 24*1024 MiB bar would reject upstream's
    # own validated reference GPU by 12 MiB.
    min_vram_mib = int(float(y.get("min_vram_gb", 24)) * 1000)
    if not gpus:
        report.error = (
            "no NVIDIA GPU detected (hardware_audit/v1 gpus is empty); "
            "YuE2 needs a BF16 GPU with >= "
            f"{y.get('min_vram_gb', 24)} GB VRAM"
        )
        return report.emit(False, 2)
    top_vram = max(int(g["memory_total_mib"]) for g in gpus)
    if top_vram < min_vram_mib:
        report.error = (
            f"largest GPU has {top_vram} MiB VRAM but [yue2].min_vram_gb="
            f"{y.get('min_vram_gb', 24)} requires >= {min_vram_mib} MiB"
        )
        return report.emit(False, 2)
    report.skipped.append(
        f"hardware gate passed: {gpus[0]['name']} with {top_vram} MiB VRAM"
    )
    report.warnings.append(
        f"YuE2 also documents >= {y.get('min_host_ram_gb', 24)} GB host RAM; "
        "WSL does not report host RAM reliably, so check it by hand"
    )

    # --- Step 2: runtime + python -------------------------------------------
    probe = rt.bash("echo runtime-ok", timeout=120)
    if not probe.ok:
        # wsl.exe reports its own failures (missing distro, access denied) on
        # stdout, so surface both streams or the reason is invisible.
        detail = tail(((probe.err or "") + "\n" + (probe.out or "")).strip(), 3) or "no output"
        report.error = f"runtime {rt.mode!r} is not usable: {detail}"
        if "access is denied" in detail.lower():
            report.error += (
                " - WSL refused access; confirm the distro runs with: "
                f"wsl.exe -d {rt.distro} -u {rt.user} -- echo ok"
            )
        elif rt.mode == "wsl":
            report.error += (
                " - install the distro with: "
                "wsl.exe --install -d Ubuntu-24.04 --no-launch --web-download"
            )
        return report.emit(False, 2)
    report.skipped.append(f"runtime reachable ({rt.mode})")

    py = str(y.get("python", "python3.12"))
    py_probe = rt.bash(f"{py} --version", timeout=120)
    if not py_probe.ok:
        report.error = (
            f"{py} not found inside the runtime ({py_probe.err.strip()}); "
            "install it (e.g. apt-get install -y python3.12 python3.12-venv) or set "
            "[yue2].python to an interpreter that exists"
        )
        return report.emit(False, 2)
    report.skipped.append(f"interpreter: {py_probe.out.strip() or py}")

    venv = rt.path(str(y.get("venv_dir", "")))
    weights = rt.path(str(y.get("weights_dir", "")))
    src = rt.path(str(y.get("src_dir", "")))
    report.venv_dir = venv
    report.weights_dir = weights
    if venv is None or weights is None:
        report.error = "cannot resolve [yue2].venv_dir/weights_dir inside the runtime"
        return report.emit(False, 2)

    # --- Step 3: pinned upstream checkout -----------------------------------
    if install_source == "checkout":
        if src is None:
            report.error = "cannot resolve [yue2].src_dir inside the runtime"
            return report.emit(False, 2)
        have_src = rt.bash(f'test -f "{src}/pyproject.toml"', timeout=120)
        if have_src.ok:
            report.skipped.append(f"upstream checkout present: {src}")
        else:
            report.actions.append("fetch pinned upstream checkouts (fetch_upstream.sh)")
            fetch = subprocess.run(
                ["bash", str(repo_root / "scripts" / "fetch_upstream.sh")],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=1800,
                check=False,
            )
            if not (repo_root / str(y.get("src_dir", "")) / "pyproject.toml").is_file():
                report.error = (
                    "upstream checkout missing after fetch_upstream.sh: "
                    f"{repo_root / str(y.get('src_dir', ''))} "
                    f"(rc={fetch.returncode}) - needs git and network on the host; "
                    "see scripts/fetch_upstream.sh output"
                )
                return report.emit(False, 8)
            report.actions.append(f"fetched {y.get('src_dir')}")

    # --- Step 4/5: venv + install -------------------------------------------
    venv_has_python = rt.bash(f'test -x "{venv}/bin/python"', timeout=120)
    if not venv_has_python.ok:
        report.actions.append(f"create venv {venv}")
        made = rt.bash(f'{py} -m venv "{venv}"', timeout=900)
        if not made.ok:
            report.error = (
                f"venv creation failed: {tail(made.err or made.out)} "
                "(on Debian/Ubuntu install the venv package: apt-get install -y python3.12-venv)"
            )
            return report.emit(False, 8)
    else:
        report.skipped.append(f"venv present: {venv}")

    cli = f"{venv}/bin/yue2"
    already = rt.bash(f'test -x "{cli}"', timeout=120).ok
    if already and not args.force:
        report.installed_version = installed_yue2_version(rt, venv)
        report.skipped.append(
            f"yue2 already installed ({report.installed_version or 'version unknown'})"
        )
    else:
        report.actions.append("upgrade pip in the venv")
        pipe = rt.bash(f'{venv}/bin/python -m pip install --upgrade pip', timeout=1800)
        if not pipe.ok:
            report.error = f"pip upgrade failed: {tail(pipe.err or pipe.out)}"
            return report.emit(False, 8)

        if install_source == "wheel":
            target = str(y.get("release_wheel", ""))
            report.warnings.append(
                "install_source=wheel: the v0.1.6 release archive bundles first-party "
                "code under CC BY-NC 4.0 as well as the weights; prefer 'checkout'"
            )
        else:
            target = src or ""
        report.actions.append(f"pip install {target}")
        inst = rt.bash(
            f'{venv}/bin/python -m pip install "{target}"', timeout=DEFAULT_TIMEOUT_S
        )
        if not inst.ok or not rt.bash(f'test -x "{cli}"', timeout=120).ok:
            report.error = (
                f"installing YuE2 failed (pip rc={inst.rc}): {tail(inst.err or inst.out, 40)}"
            )
            return report.emit(False, 8)
        report.installed_version = installed_yue2_version(rt, venv)
        report.actions.append("yue2 installed")

    # --- Step 6: weights ----------------------------------------------------
    hf_models = [str(m) for m in (y.get("hf_models") or [])]
    if args.skip_weights:
        report.skipped.append("--skip-weights: weight download skipped")
        report.warnings.append("weights were not verified; generation will fetch them on first use")
    else:
        hf = f"{venv}/bin/hf"
        if not rt.bash(f'test -x "{hf}"', timeout=120).ok:
            report.error = (
                f"the `hf` CLI is missing from the venv ({hf}); huggingface_hub should "
                "have installed it - re-run with --force, or pip install it manually"
            )
            return report.emit(False, 8)
        for repo_id in hf_models:
            slug = repo_id.replace("/", "--")
            cached = rt.bash(f'test -d "{weights}/hub/models--{slug}"', timeout=120).ok
            if cached and not args.force:
                report.weights_present[repo_id] = True
                report.skipped.append(f"weights present: {repo_id}")
                continue
            report.actions.append(f"download weights {repo_id} (~7.8 GB total for YuE2)")
            dl = rt.bash(
                f'HF_HOME="{weights}" "{hf}" download {repo_id}', timeout=DEFAULT_TIMEOUT_S
            )
            present = rt.bash(f'test -d "{weights}/hub/models--{slug}"', timeout=120).ok
            report.weights_present[repo_id] = present
            if not dl.ok or not present:
                report.error = (
                    f"weight download failed for {repo_id} (rc={dl.rc}): "
                    f"{tail(dl.err or dl.out)}"
                )
                return report.emit(False, 8)

    # --- Step 7: doctor + CUDA gates ---------------------------------------
    nv = rt.bash(
        "nvidia-smi --query-gpu=name,memory.total --format=csv,noheader", timeout=180
    )
    report.cuda_visible = nv.ok and bool(nv.out.strip())
    if report.cuda_visible:
        report.skipped.append(f"CUDA visible in runtime: {nv.out.strip().splitlines()[0]}")
    else:
        report.warnings.append(
            "nvidia-smi is not usable inside the runtime; YuE2 needs GPU passthrough. "
            "Reinstall the NVIDIA Windows driver, reboot WSL (wsl.exe --shutdown), retest."
        )

    doc = rt.bash(f'"{cli}" doctor', timeout=1800)
    report.doctor_ok = doc.ok
    report.doctor_tail = tail(doc.out or doc.err, 30)
    if not doc.ok:
        report.warnings.append(
            "`yue2 doctor` returned non-zero; inspect doctor_tail before generating"
        )

    ok = report.error is None
    return report.emit(ok, 0 if ok else 8)


if __name__ == "__main__":
    sys.exit(main())
