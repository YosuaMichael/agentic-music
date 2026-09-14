#!/usr/bin/env python3
"""Produce, review and render YuE2's symbolic score — and generate takes.

Usage:
    # 1. SCORE FIRST (no audio, ~18 s): plan the composition and stop
    python scripts/generate_yue2.py --session studio/sessions/<song-id> --seed 7 \
        --stage plan

    # 2. RENDER the approved score (~42 s): reproduces the planned song exactly;
    #    an edited score renders the edited composition
    python scripts/generate_yue2.py --session studio/sessions/<song-id> \
        --from-plan studio/sessions/<song-id>/plans/plan-01

    # 2b. render an edited copy of that score
    python scripts/generate_yue2.py --session studio/sessions/<song-id> \
        --from-plan studio/sessions/<song-id>/plans/plan-01 --score-file my-edit.abc

    # 3. one-shot (plan + audio, unchanged):
    python scripts/generate_yue2.py --session studio/sessions/<song-id> --seed 831001 \
        [--cot full|melody|off] [--take-id N] [--extra-arg "<yue2 flag>"]... \
        [--config configs/provider.toml]

Score-first exists because YuE2 plans an editable ABC composition before it
renders audio, and that plan is the model's real creative decision — so it is
worth approving (or fixing) before paying for a render. Measured on an RTX 4090:
plan 18.4 s vs render 41.9 s vs one-shot 54.7 s, and rendering an unedited plan
reproduced the one-shot take BYTE-IDENTICALLY (plan decision S4).

Reading style.txt (the short YuE2 style prompt) and lyrics.txt from the session,
it writes:

    # --stage plan
    studio/sessions/<song-id>/plans/plan-NN/                # upstream plan bundle:
                                                            #   score.abc, plan.json,
                                                            #   abc_tokens.npy, prefix.npy,
                                                            #   plan_manifest.json
    studio/sessions/<song-id>/plans/plan-NN.request.json    # exact request sent
    studio/sessions/<song-id>/plans/plan-NN.style.txt       # provenance snapshots
    studio/sessions/<song-id>/plans/plan-NN.lyrics.txt

    # audio (one-shot or --from-plan)
    studio/sessions/<song-id>/takes/take-NN.wav             # PCM master (judging)
    studio/sessions/<song-id>/takes/take-NN.flac            # upstream original
    studio/sessions/<song-id>/takes/take-NN.metadata.json
    studio/sessions/<song-id>/takes/take-NN.request.json    # exact request sent
    studio/sessions/<song-id>/takes/take-NN.style.txt       # prompt snapshot
    studio/sessions/<song-id>/takes/take-NN.yue2/           # score.abc, result.json,
                                                            # latent.npy, generate.log
    studio/sessions/<song-id>/takes/take-NN.mp3             # when [yue2].mp3

A plan is not a take: plans live in their own namespace, carry no audio, and a
take records which plan (and which exact score bytes) produced it —
`rendered_from: {plan, score_sha256, score_edited, plan_score_sha256}`.

Model-specific limits, all deliberate:
  * YuE2 requires lyrics and has NO instrumental mode, so an empty lyrics.txt is
    refused with exit 2 instead of being sent as a broken request (decision Y9).
  * No duration/length control exists; the score IS the form (decision Y8), which
    is a further reason to review it before rendering.
  * `cot=off` sketches no score, so --stage plan is refused for it (nothing to
    review).

Setup: python scripts/setup_yue2.py. WEIGHTS ARE CC BY-NC 4.0 (non-commercial).

JSON contracts (stdout):
  plan/v1      (--stage plan)
    {"schema": "plan/v1", "ok": true, "provider": "yue2", "model": "...",
     "cot": "full", "seed": 7, "plan": "studio/.../plans/plan-01",
     "plan_name": "plan-01", "score_abc": ".../plans/plan-01/score.abc",
     "score_sha256": "...", "score_lines": 42, "score_preview": "X:1\\n...",
     "plan_json": "...", "request": "...", "style_source": "style.txt",
     "truncated": false, "elapsed_s": 18.4, "next": "...", "error": null}

  generate/v1  (audio, identical shape to scripts/generate.py and
                scripts/generate_audiocpp.py, plus additive provider fields)
    {"schema": "generate/v1", "ok": true, "provider": "yue2", "model": "...",
     "cot": "full", "truncated": false, "rtf": 0.34, "take": "take-01",
     "wav": "...", "flac": "...", "metadata": "...", "native_dir": "...",
     "bytes": 123, "elapsed_s": 71.4, "rendered_from": {...}, "error": null}
Adding optional keys is non-breaking under our schema policy.

Exit codes: 0 success; 2 bad inputs/config; 8 upstream CLI execution failure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import struct
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI_TIMEOUT_S = 7200
SCORE_PREVIEW_LINES = 40

# Flags THIS generator owns because they define provenance: the frozen
# request.json must describe exactly what the model received, and the output must
# land where the session contract says. Everything else the upstream `yue2` CLI
# accepts (--quantization, --offload-ar, --backend, --device, --budget, --vae,
# --vae-revision, --revision, --model, --quiet, …) may be passed through
# --extra-arg — see the model-guide skill.
RESERVED_EXTRA_FLAGS = frozenset(
    {
        "--request",
        "--output",
        "--id",
        "--style",
        "--lyrics",
        "--lyrics-file",
        "--abc-file",
        "--seed",
        "--cot",
        "--cfg-scale",
        "--stage",
    }
)


def split_extra_args(raw_values: list[str]) -> tuple[list[str], str | None]:
    """Shell-split repeatable --extra-arg values; reject provenance-breaking ones."""
    tokens: list[str] = []
    for raw in raw_values:
        try:
            parts = shlex.split(raw)
        except ValueError as exc:
            return [], f"--extra-arg {raw!r} is not shell-parseable: {exc}"
        for token in parts:
            flag = token.split("=", 1)[0]
            if flag in RESERVED_EXTRA_FLAGS:
                return [], (
                    f"--extra-arg may not set {flag}: it would desynchronise the frozen "
                    "request from what the model received. Use the first-class flag "
                    "(--cot / --stage / --from-plan) or a [yue2] config key instead."
                )
        tokens += parts
    return tokens, None


def fail(message: str, code: int = 2) -> int:
    print(json.dumps({"schema": "generate/v1", "ok": False, "provider": "yue2", "error": message}))
    return code


def fail_plan(message: str, code: int = 2) -> int:
    print(json.dumps({"schema": "plan/v1", "ok": False, "provider": "yue2", "error": message}))
    return code


def tail(text: str, lines: int = 25) -> str:
    return "\n".join(text.splitlines()[-lines:])


def display_path(path: Path) -> str:
    """Repo-relative POSIX path when possible, so output is machine-independent."""
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
            absolute = candidate  # e.g. C:\repo\... — still mappable onto /mnt/c
        else:
            absolute = (self.repo_root / configured).resolve()
        if self.mode == "native":
            return str(absolute)
        drive = absolute.drive.rstrip(":").lower()
        if not drive:
            return None
        tail_path = absolute.as_posix().split(":", 1)[-1]
        return f"/mnt/{drive}{tail_path}"

    def file_path(self, path: Path) -> str | None:
        """Map an absolute host path into the runtime (used for session dirs)."""
        return self.path(str(path))


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #


def read_style(session: Path) -> tuple[str, str]:
    """Return (style text, source label). Prefers the model-native style.txt."""
    style_path = session / "style.txt"
    if style_path.is_file():
        # utf-8-sig: a BOM-prefixed empty file must still read as empty (editors
        # and PowerShell's -Encoding utf8 happily write one).
        text = style_path.read_text(encoding="utf-8-sig").strip()
        if text:
            return " ".join(line.strip() for line in text.splitlines() if line.strip()), "style.txt"
    # Fallback for sessions composed before YuE2 existed: the caption's own brief
    # summary is a short prompt-shaped string. Flagged so a degraded prompt is
    # visible rather than silent (plan decision Y5).
    caption_json = session / "caption.json"
    if caption_json.is_file():
        try:
            data = json.loads(caption_json.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            data = {}
        description = str(((data.get("inputs") or {}).get("description")) or "").strip()
        if description:
            return " ".join(description.split()), "caption.json"
    return "", "missing"


def truthy_truncated(value: object) -> bool:
    """Upstream reports truncation as a bool or a per-stage dict."""
    if isinstance(value, dict):
        return any(bool(v) for v in value.values())
    return bool(value)


def find_audio(out_dir: Path, take_name: str) -> Path | None:
    """Locate the produced FLAC: upstream nests it under the request id."""
    candidates = [
        out_dir / take_name / "audio.flac",
        out_dir / "audio.flac",
    ]
    for path in candidates:
        if path.is_file() and path.stat().st_size > 0:
            return path
    nested = sorted(out_dir.glob("*/audio.flac"))
    return nested[0] if nested else None


def find_score(out_dir: Path, name: str) -> Path | None:
    """Locate the planned score: upstream nests it under the request id."""
    candidates = [out_dir / name / "score.abc", out_dir / "score.abc"]
    for path in candidates:
        if path.is_file() and path.stat().st_size > 0:
            return path
    nested = sorted(out_dir.glob("*/score.abc"))
    return nested[0] if nested else None


def read_result_json(native_dir: Path) -> dict:
    path = native_dir / "result.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def read_plan_meta(plan_dir: Path) -> dict:
    """Read a saved plan's request/timing plus its integrity manifest."""
    meta: dict = {"plan_json": None, "manifest": None, "request": {}, "truncated": None}
    plan_json = plan_dir / "plan.json"
    if plan_json.is_file():
        try:
            data = json.loads(plan_json.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                meta["request"] = data.get("request") or {}
                meta["truncated"] = data.get("truncated")
                meta["timing"] = data.get("timing")
                meta["plan_json"] = plan_json
        except json.JSONDecodeError:
            pass
    manifest = plan_dir / "plan_manifest.json"
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                meta["manifest"] = data
        except json.JSONDecodeError:
            pass
    return meta


def score_edit_state(plan_dir: Path, score_path: Path) -> bool | None:
    """Has this score been edited since planning?

    True/False when the plan's integrity manifest can answer it (it carries the
    sha256 of the planned score.abc), None when the manifest is missing or does
    not cover the score. Verified against upstream: the manifest is exactly what
    SymbolicPlan.load uses to refuse a modified plan.
    """
    meta = read_plan_meta(plan_dir)
    manifest = meta.get("manifest") or {}
    planned = manifest.get("score.abc")
    if not planned or not score_path.is_file():
        return None
    return sha256_file(score_path) != planned


def score_preview(score_path: Path, max_lines: int = SCORE_PREVIEW_LINES) -> str:
    try:
        lines = score_path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return ""
    shown = lines[:max_lines]
    if len(lines) > max_lines:
        shown.append(f"… ({len(lines) - max_lines} more lines in {score_path.name})")
    return "\n".join(shown)


def wav_format(path: Path) -> tuple[int, int]:
    """Read (sample_rate, channels) from the WAV header — never assume."""
    with path.open("rb") as fh:
        header = fh.read(44)
    if header[:4] != b"RIFF" or header[8:12] != b"WAVE":
        raise ValueError("not a RIFF/WAVE WAV")
    channels, sample_rate = struct.unpack("<HI", header[22:28])
    return sample_rate, channels


def retire_stale_dir(out_dir: Path) -> str | None:
    """Upstream refuses a non-empty output dir, so keep old evidence instead.

    Follows the repo's `_failed` convention: never delete failed evidence, just
    move it aside so the retry can start fresh.
    """
    if not out_dir.exists():
        return None
    retired = out_dir.with_name(out_dir.name + "_failed")
    counter = 2
    while retired.exists():
        retired = out_dir.with_name(f"{out_dir.name}_failed-{counter}")
        counter += 1
    out_dir.rename(retired)
    return display_path(retired)


def next_index(directory: Path, prefix: str) -> int:
    """Next free NN for `<prefix>-NN` entries (dirs or `<prefix>-NN.*` files)."""
    numbers: list[int] = []
    if directory.is_dir():
        for entry in directory.iterdir():
            match = re.fullmatch(rf"{prefix}-(\d+)(\..*)?", entry.name)
            if match:
                numbers.append(int(match.group(1)))
    return (max(numbers) + 1) if numbers else 1


# --------------------------------------------------------------------------- #
# Shared setup
# --------------------------------------------------------------------------- #


@dataclass
class Context:
    session: Path
    lyrics: str
    lyrics_path: Path
    style: str
    style_source: str
    cfg: dict
    yue2: dict
    rt: Runtime
    cli: str
    extra_tokens: list[str]


def prepare_context(args: argparse.Namespace) -> tuple[Context | None, int | None]:
    """Validate inputs and locate the runtime. Returns (context, error_code)."""
    session: Path = args.session
    if not session.is_dir():
        return None, fail(f"session directory does not exist: {session}")
    lyrics_path = session / "lyrics.txt"
    if not lyrics_path.is_file():
        return None, fail(f"missing {lyrics_path}")

    lyrics = lyrics_path.read_text(encoding="utf-8-sig")
    if not lyrics.strip():
        # Upstream requires lyrics and has no instrumental mode (decision Y9), and
        # neither does the other shipped model (2026-09-14 correction).
        return None, fail(
            f"{lyrics_path} is empty: YuE2 has no instrumental mode (upstream 'lyrics' "
            "is a required field). No shipped model can do instrumental-only — "
            "MiniMax Music 3 has no instrumental mode either and has always produced "
            "vocals. Write lyrics with section tags, or tell the user instrumental-only "
            "is unsupported: plans/2026-09-14-instrumental-generation-unsupported.md"
        )

    style, style_source = read_style(session)
    if not style:
        return None, fail(
            f"missing style prompt: {session / 'style.txt'} is absent/empty and "
            "caption.json has no inputs.description. compose-brief writes style.txt "
            "(one comma-separated line: language, genre, vocal character, 2-3 "
            "instruments, tempo)."
        )

    if not args.config.is_file():
        return None, fail(f"config not found: {args.config}")
    try:
        cfg = tomllib.loads(args.config.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        return None, fail(f"config is not valid TOML: {exc}")
    y = cfg.get("yue2")
    if not y:
        return None, fail("[yue2] section missing from config")

    rt = Runtime(y, REPO_ROOT)
    if rt.mode not in ("wsl", "native"):
        return None, fail(f"unknown [yue2].runtime {rt.mode!r}")
    venv = rt.path(str(y.get("venv_dir", "")))
    if venv is None:
        return None, fail(
            "cannot resolve [yue2].venv_dir inside the runtime"
            + (" (is WSL installed and running?)" if rt.mode == "wsl" else "")
        )
    cli = f"{venv}/bin/yue2"
    if not rt.bash(f'test -x "{cli}"', timeout=120).ok:
        return None, fail(
            f"YuE2 is not installed at {cli} - run: python scripts/setup_yue2.py",
            code=2,
        )

    return (
        Context(
            session=session,
            lyrics=lyrics,
            lyrics_path=lyrics_path,
            style=style,
            style_source=style_source,
            cfg=cfg,
            yue2=y,
            rt=rt,
            cli=cli,
            extra_tokens=[],
        ),
        None,
    )


def base_cli_args(ctx: Context) -> list[str]:
    """Model/VAE/offline/extra flags common to the plan and audio invocations."""
    y = ctx.yue2
    cmd: list[str] = []
    model = str(y.get("model", "") or "").strip()
    if model:
        cmd += ["--model", ctx.rt.path(model) or model]
    vae = str(y.get("vae", "") or "").strip()
    if vae:
        cmd += ["--vae", vae]
    if y.get("offline"):
        cmd += ["--offline"]
    cmd += [str(a) for a in (y.get("extra_generate_args") or [])]
    cmd += ctx.extra_tokens
    return cmd


def snapshot_provenance(session: Path, dest_dir: Path, stem: str, lyrics_path: Path) -> None:
    for src, suffix in (
        (session / "style.txt", ".style.txt"),
        (session / "caption.md", ".caption.md"),
        (lyrics_path, ".lyrics.txt"),
        (session / "caption.json", ".caption.json"),
    ):
        if src.is_file():
            shutil.copyfile(src, dest_dir / f"{stem}{suffix}")


# --------------------------------------------------------------------------- #
# Mode: --stage plan  (score first, no audio)
# --------------------------------------------------------------------------- #


def run_plan(ctx: Context, args: argparse.Namespace) -> int:
    cot = args.cot or str(ctx.yue2.get("cot", "full"))
    if cot == "off":
        return fail_plan(
            "--stage plan with cot=off has nothing to review: cot=off sketches no "
            "symbolic score by design. Use --cot full (melody + chords) or "
            "--cot melody, or skip planning and render one-shot."
        )

    plans_dir = ctx.session / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    plan_num = args.plan_id if args.plan_id is not None else next_index(plans_dir, "plan")
    plan_name = f"plan-{plan_num:02d}"
    out_dir = plans_dir / plan_name

    cfg_scale = float(ctx.yue2.get("cfg_scale", 0.0) or 0.0)
    request: dict[str, object] = {
        "id": plan_name,
        "style": ctx.style,
        "lyrics": ctx.lyrics,
        "cot": cot,
        "seed": args.seed,
    }
    if cfg_scale > 0:
        request["cfg_scale"] = cfg_scale
    request_path = plans_dir / f"{plan_name}.request.json"
    request_path.write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")

    request_rt = ctx.rt.file_path(request_path)
    plans_dir_rt = ctx.rt.file_path(plans_dir)
    if request_rt is None or plans_dir_rt is None:
        return fail_plan("cannot map the plans directory into the runtime")

    retired = retire_stale_dir(out_dir)
    cmd = [ctx.cli, "generate", "--request", request_rt, "--output", plans_dir_rt, "--stage", "plan"]
    cmd += base_cli_args(ctx)

    started = time.monotonic()
    res = ctx.rt.run(cmd, timeout=CLI_TIMEOUT_S)
    elapsed = round(time.monotonic() - started, 1)

    score = find_score(out_dir, plan_name)
    if score is None:
        sys.stderr.write(
            f"[generate_yue2] yue2 --stage plan rc={res.rc}\n"
            f"--- stdout tail ---\n{tail(res.out)}\n--- stderr tail ---\n{tail(res.err, 40)}\n"
        )
        return fail_plan(
            f"yue2 --stage plan produced no score.abc (rc={res.rc}); see stderr tail. "
            f"Attempt artifacts kept in {plan_name}",
            code=8,
        )

    native_dir = score.parent
    log_path: Path | None = native_dir / "generate.log"
    try:
        log_path.write_text(
            f"--- yue2 generate --stage plan stdout ---\n{res.out}\n"
            f"--- stderr ---\n{res.err}\n",
            encoding="utf-8",
        )
    except OSError:
        log_path = None

    snapshot_provenance(ctx.session, plans_dir, plan_name, ctx.lyrics_path)
    meta = read_plan_meta(out_dir)
    preview = score_preview(score)
    score_lines = len(preview.splitlines())

    out: dict[str, object] = {
        "schema": "plan/v1",
        "ok": True,
        "provider": "yue2",
        "model": request_model_name(ctx),
        "cot": cot,
        "seed": args.seed,
        "plan": display_path(out_dir),
        "plan_name": plan_name,
        "score_abc": display_path(score),
        "score_sha256": sha256_file(score),
        "score_lines": score_lines,
        "score_preview": preview,
        "plan_json": display_path(native_dir / "plan.json")
        if (native_dir / "plan.json").is_file()
        else None,
        "plan_manifest": display_path(native_dir / "plan_manifest.json")
        if (native_dir / "plan_manifest.json").is_file()
        else None,
        "request": display_path(request_path),
        "generate_log": display_path(log_path) if log_path else None,
        "style_source": ctx.style_source,
        "truncated": truthy_truncated(meta.get("truncated")),
        "elapsed_s": elapsed,
        "retired_previous_attempt": retired,
        "next": (
            "Show the score to the user, then render the approved version with "
            f"--from-plan {display_path(out_dir)} (or edit a copy and pass it as "
            "--score-file). Rendering an unedited plan reproduces the planned song "
            "byte-identically."
        ),
        "error": None,
    }
    print(json.dumps(out, indent=2))
    return 0


def request_model_name(ctx: Context) -> str:
    return str(ctx.yue2.get("model", "") or "").strip() or "m-a-p/YuE2-3B"


# --------------------------------------------------------------------------- #
# Mode: audio (one-shot, or --from-plan)
# --------------------------------------------------------------------------- #


def resolve_plan_inputs(ctx: Context, args: argparse.Namespace) -> tuple[dict | None, int | None]:
    """Resolve seed/cot/score from an approved plan. Returns (info, error_code)."""
    plan_dir = args.from_plan
    if not plan_dir.is_absolute():
        candidate = REPO_ROOT / plan_dir
        plan_dir = candidate if candidate.exists() else (ctx.session / plan_dir)
    if not plan_dir.is_dir():
        return None, fail(f"--from-plan is not a directory: {plan_dir}")

    meta = read_plan_meta(plan_dir)
    plan_request = meta.get("request") or {}
    if args.score_file is not None:
        score = args.score_file if args.score_file.is_absolute() else (REPO_ROOT / args.score_file)
        if not score.is_file():
            return None, fail(f"--score-file not found: {score}")
        source = "score-file"
    else:
        score = find_score(plan_dir, plan_dir.name)
        if score is None:
            return None, fail(
                f"no score.abc under {plan_dir} - is that a --stage plan output? "
                "Pass --score-file to supply your own ABC."
            )
        source = "plan"

    seed = args.seed if args.seed is not None else plan_request.get("seed")
    if seed is None:
        return None, fail(
            "cannot determine the seed: pass --seed, or point --from-plan at a plan "
            "whose plan.json records one."
        )
    cot = args.cot or str(plan_request.get("cot") or ctx.yue2.get("cot", "full"))
    if cot == "off":
        return None, fail(
            "--cot off cannot render a supplied score: upstream requires cot=full or "
            "cot=melody when an ABC score is provided."
        )
    return (
        {
            "plan_dir": plan_dir,
            "score": score,
            "score_source": source,
            "seed": int(seed),
            "cot": cot,
            # Compare bytes against the plan's own manifest either way: a verbatim
            # copy of the planned score supplied via --score-file is NOT an edit.
            "edited": score_edit_state(plan_dir, score),
            "plan_score_sha256": (meta.get("manifest") or {}).get("score.abc"),
            "seed_overridden": args.seed is not None and args.seed != plan_request.get("seed"),
        },
        None,
    )


def run_audio(ctx: Context, args: argparse.Namespace) -> int:
    y = ctx.yue2
    session = ctx.session
    takes_dir = session / "takes"
    takes_dir.mkdir(parents=True, exist_ok=True)

    plan_info: dict | None = None
    score_rt: str | None = None
    if args.from_plan is not None:
        plan_info, error = resolve_plan_inputs(ctx, args)
        if error is not None:
            return error
        assert plan_info is not None
        # Validate the score's runtime mapping BEFORE allocating a take number or
        # writing a request, so a bad path cannot burn a take id.
        score_rt = ctx.rt.file_path(Path(plan_info["score"]))
        if score_rt is None:
            return fail(f"cannot map {plan_info['score']} into the runtime")
        seed = int(plan_info["seed"])
        cot = str(plan_info["cot"])
    else:
        if args.seed is None and args.take_id is None:
            return fail("--seed is required unless you render from an approved score (--from-plan)")
        seed = int(args.seed if args.seed is not None else 0)
        cot = args.cot or str(y.get("cot", "full"))

    if args.take_id is not None:
        take_num = args.take_id
    else:
        take_num = next_index(takes_dir, "take")
    take_name = f"take-{take_num:02d}"
    wav_path = takes_dir / f"{take_name}.wav"
    flac_path = takes_dir / f"{take_name}.flac"
    meta_path = takes_dir / f"{take_name}.metadata.json"
    request_path = takes_dir / f"{take_name}.request.json"

    cfg_scale = float(y.get("cfg_scale", 0.0) or 0.0)
    # Only documented request keys: upstream raises ValueError on unknown fields.
    request: dict[str, object] = {
        "id": take_name,
        "style": ctx.style,
        "lyrics": ctx.lyrics,
        "cot": cot,
        "seed": seed,
    }
    if cfg_scale > 0:
        request["cfg_scale"] = cfg_scale
    request_path.write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")

    request_rt = ctx.rt.file_path(request_path)
    if request_rt is None:
        return fail(f"cannot map {request_path} into the runtime")
    out_dir = takes_dir / f"{take_name}.yue2"
    out_dir_rt = ctx.rt.file_path(out_dir)
    if out_dir_rt is None:
        return fail(f"cannot map {out_dir} into the runtime")
    retired = retire_stale_dir(out_dir)

    cmd = [ctx.cli, "generate", "--request", request_rt, "--output", out_dir_rt]
    if score_rt is not None:
        cmd += ["--abc-file", score_rt]
    cmd += base_cli_args(ctx)

    started = time.monotonic()
    res = ctx.rt.run(cmd, timeout=CLI_TIMEOUT_S)
    elapsed = round(time.monotonic() - started, 1)

    audio = find_audio(out_dir, take_name)
    if audio is None:
        # Preserve everything the attempt produced; the native dir stays put.
        sys.stderr.write(
            f"[generate_yue2] yue2 CLI rc={res.rc}\n"
            f"--- stdout tail ---\n{tail(res.out)}\n--- stderr tail ---\n{tail(res.err, 40)}\n"
        )
        return fail(
            f"yue2 CLI produced no audio (rc={res.rc}); see stderr tail. "
            f"Attempt artifacts kept in {out_dir.name}",
            code=8,
        )

    native_dir = audio.parent
    result = read_result_json(native_dir)
    truncated = truthy_truncated(result.get("truncated"))

    # Keep the model's own progress log (it reports stage elapsed times and token
    # throughput). Useful for benchmarking and for debugging a bad take, and it
    # costs nothing to retain since the native bundle is already kept.
    log_path: Path | None = native_dir / "generate.log"
    try:
        log_path.write_text(
            f"--- yue2 generate stdout ---\n{res.out}\n"
            f"--- yue2 generate stderr ---\n{res.err}\n",
            encoding="utf-8",
        )
    except OSError:
        log_path = None

    # --- master WAV ---------------------------------------------------------
    if shutil.which("ffmpeg") is None:
        return fail(
            "ffmpeg not found on PATH (install via: winget install Gyan.FFmpeg)",
            code=2,
        )
    sample_rate_cfg = int(y.get("sample_rate", 48000))
    conv = subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(audio),
            "-ar", str(sample_rate_cfg), "-ac", "2",
            "-c:a", "pcm_s16le",
            str(wav_path),
        ],
        capture_output=True,
        text=True,
        timeout=1800,
        check=False,
    )
    if conv.returncode != 0 or not wav_path.is_file():
        return fail(
            f"ffmpeg could not convert {audio.name} to WAV (rc={conv.returncode}): "
            f"{tail(conv.stderr or '', 5)}",
            code=8,
        )
    shutil.copyfile(audio, flac_path)

    snapshot_provenance(session, takes_dir, take_name, ctx.lyrics_path)

    size = wav_path.stat().st_size
    sample_rate, channels = wav_format(wav_path)
    audio_s = size / (sample_rate * channels * 2)  # PCM16
    rtf = round(elapsed / audio_s, 2) if audio_s > 0 else None

    rendered_from: dict[str, object] | None = None
    if plan_info is not None:
        rendered_from = {
            "plan": display_path(Path(plan_info["plan_dir"])),
            "score_source": plan_info["score_source"],
            "score_sha256": sha256_file(Path(plan_info["score"])),
            "plan_score_sha256": plan_info["plan_score_sha256"],
            "score_edited": plan_info["edited"],
            "seed_overridden": plan_info["seed_overridden"],
        }

    metadata = {
        "schema": "generate_meta/v1",
        "provider": "yue2",
        "take": take_name,
        "endpoint": "local-cli",
        "model": request_model_name(ctx),
        "vae": str(y.get("vae", "") or "").strip() or "standard",
        "seed": seed,
        "cot": cot,
        "cfg_scale": cfg_scale or None,
        "style_source": ctx.style_source,
        # Recorded so the frozen request stays honest about model-native overrides.
        "extra_args": ctx.extra_tokens or None,
        "truncated": truncated,
        "audio_seconds": result.get("audio_seconds"),
        "sample_rate_hz": sample_rate,
        "channels": channels,
        "bytes": size,
        "elapsed_s": elapsed,
        "started_utc": datetime.now(UTC).isoformat(),
        "rendered_from": rendered_from,
        "artifacts": {
            "wav": str(wav_path),
            "flac": str(flac_path),
            "request": str(request_path),
            "native_dir": str(native_dir),
            "score_abc": str(native_dir / "score.abc") if (native_dir / "score.abc").is_file() else None,
            "generate_log": str(log_path) if log_path else None,
            "retired_previous_attempt": retired,
        },
    }
    meta_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    out: dict[str, object] = {
        "schema": "generate/v1",
        "ok": True,
        "provider": "yue2",
        "model": metadata["model"],
        "cot": cot,
        "truncated": truncated,
        "rtf": rtf,
        "take": take_name,
        "wav": str(wav_path),
        "flac": str(flac_path),
        "metadata": str(meta_path),
        "native_dir": str(native_dir),
        "bytes": size,
        "elapsed_s": elapsed,
        "error": None,
    }
    if retired:
        out["retired_previous_attempt"] = retired
    if ctx.extra_tokens:
        out["extra_args"] = ctx.extra_tokens
    if rendered_from:
        out["rendered_from"] = rendered_from
        if rendered_from["score_edited"] is False:
            out["note"] = (
                "rendered from an unedited approved score: reproduces the planned song "
                "byte-identically on the same machine and settings"
            )
        elif rendered_from["score_edited"] is True:
            out["note"] = "rendered from an EDITED score: this is a new performance of it"
    if truncated:
        out["warning"] = (
            "upstream reported truncation; the audio is playable but the model hit a "
            "token limit - consider shorter/looser lyrics"
        )

    if y.get("mp3"):
        tr = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "transcode.py"),
                "--audio", str(wav_path),
                "--quality", str(y.get("mp3_quality", 2)),
            ],
            capture_output=True,
            text=True,
            timeout=1800,
            check=False,
        )
        try:
            tr_out = json.loads(tr.stdout or "{}")
        except json.JSONDecodeError:
            tr_out = {}
        if tr.returncode == 0 and tr_out.get("ok") and tr_out.get("outputs"):
            mp3 = Path(tr_out["outputs"][0]["mp3"])
            out["mp3"] = str(mp3)
            out["mp3_bytes"] = mp3.stat().st_size
        else:
            sys.stderr.write(f"[generate_yue2] mp3 conversion skipped: {tr_out}\n")
            out["mp3"] = None

    print(json.dumps(out, indent=2))
    return 0


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True, type=Path)
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Required for a new take or a plan; taken from the plan's request when "
        "rendering with --from-plan",
    )
    parser.add_argument(
        "--config", type=Path, default=REPO_ROOT / "configs" / "provider.toml"
    )
    parser.add_argument(
        "--stage",
        choices=["plan", "audio"],
        default="audio",
        help="'plan' plans the symbolic score and stops (no audio); 'audio' renders",
    )
    parser.add_argument(
        "--cot",
        choices=["full", "melody", "off"],
        default=None,
        help="Override [yue2].cot: symbolic planning mode",
    )
    parser.add_argument(
        "--from-plan",
        type=Path,
        default=None,
        help="Render audio from an approved plan directory (its score.abc is supplied "
        "to the model as the composition)",
    )
    parser.add_argument(
        "--score-file",
        type=Path,
        default=None,
        help="With --from-plan: render this ABC file instead of the plan's own score "
        "(use for an edited composition)",
    )
    parser.add_argument("--take-id", type=int, default=None)
    parser.add_argument("--plan-id", type=int, default=None)
    parser.add_argument(
        "--extra-arg",
        action="append",
        default=[],
        metavar="ARGS",
        help="Upstream `yue2 generate` flag(s) forwarded verbatim (repeatable, "
        'shell-split: --extra-arg "--quantization fp8"). See the model-guide skill '
        "for the model's full vocabulary.",
    )
    args = parser.parse_args()

    if args.stage == "plan" and args.from_plan is not None:
        return fail_plan("--stage plan and --from-plan are mutually exclusive")
    if args.score_file is not None and args.from_plan is None:
        return fail("--score-file requires --from-plan (it renders that plan's composition)")
    if args.stage == "plan" and args.seed is None:
        return fail_plan("--seed is required to plan a score")

    extra_tokens, extra_error = split_extra_args(args.extra_arg)
    if extra_error:
        return fail_plan(extra_error) if args.stage == "plan" else fail(extra_error)

    if args.stage == "plan":
        ctx, error = prepare_context(args)
        if error is not None:
            return error
        assert ctx is not None
        ctx.extra_tokens = extra_tokens
        return run_plan(ctx, args)

    ctx, error = prepare_context(args)
    if error is not None:
        return error
    assert ctx is not None
    ctx.extra_tokens = extra_tokens
    return run_audio(ctx, args)


if __name__ == "__main__":
    sys.exit(main())
