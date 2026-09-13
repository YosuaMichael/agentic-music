#!/usr/bin/env python3
"""Generate one seeded take with the YuE2 music model.

Usage:
    python scripts/generate_yue2.py --session studio/sessions/<song-id> --seed 831001 \
        [--cot full|melody|off] [--take-id N] [--extra-arg "<yue2 flag>"]... \
        [--config configs/provider.toml]

Reads style.txt (the short YuE2 style prompt) and lyrics.txt from the session,
writes the exact upstream request, runs `yue2 generate` inside the configured
runtime (WSL2 on Windows, native on Linux), and produces the same session
artifacts as the other providers:

    studio/sessions/<song-id>/takes/take-NN.wav            # PCM master (judging)
    studio/sessions/<song-id>/takes/take-NN.flac           # upstream original
    studio/sessions/<song-id>/takes/take-NN.metadata.json
    studio/sessions/<song-id>/takes/take-NN.request.json   # exact request sent
    studio/sessions/<song-id>/takes/take-NN.style.txt      # prompt snapshot
    studio/sessions/<song-id>/takes/take-NN.yue2/          # score.abc, plan.json,
                                                          # result.json, latent.npy
    studio/sessions/<song-id>/takes/take-NN.mp3            # when [yue2].mp3

Model-specific limits, both deliberate (plans/2026-09-13-yue2-default-model.md):
  * YuE2 requires lyrics and has NO instrumental mode, so an empty lyrics.txt is
    refused with exit 2 instead of being sent as a broken request (decision Y9).
  * Upstream exposes no duration/length control, so there is no --duration-sec
    here; length is emergent from the model (decision Y8).

Setup: python scripts/setup_yue2.py. WEIGHTS ARE CC BY-NC 4.0 (non-commercial).

JSON contract (stdout) — generate/v1, the same shape as scripts/generate.py and
scripts/generate_audiocpp.py, with additive provider fields:
    {"schema": "generate/v1", "ok": true, "provider": "yue2", "model": "...",
     "cot": "full", "truncated": false, "rtf": 0.34, "take": "take-01",
     "wav": "...", "flac": "...", "metadata": "...", "native_dir": "...",
     "bytes": 123, "elapsed_s": 71.4, "error": null}
Adding optional keys is non-breaking under our schema policy.

Exit codes: 0 success; 2 bad inputs/config; 8 upstream CLI execution failure.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
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

# Flags THIS generator owns because they define provenance: the frozen
# take-NN.request.json must describe exactly what the model received, and the
# output must land where the session contract says. Everything else the upstream
# `yue2` CLI accepts (--quantization, --offload-ar, --backend, --device,
# --budget, --vae, --vae-revision, --revision, --model, --stage, --quiet, …) may
# be passed through --extra-arg — see the model-guide skill.
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
                    "take request from what the model received. Use the first-class flag "
                    "(--cot) or a [yue2] config key instead."
                )
        tokens += parts
    return tokens, None


def fail(message: str, code: int = 2) -> int:
    print(json.dumps({"schema": "generate/v1", "ok": False, "provider": "yue2", "error": message}))
    return code


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
        """Map a config path into the runtime: expand ~, map repo-relative paths."""
        if not configured:
            return None
        if configured.startswith("~"):
            home = self.home()
            if home is None:
                return None
            return home + configured[1:]
        if configured.startswith("/"):  # POSIX absolute: already runtime-valid
            return configured
        if Path(configured).is_absolute():
            # A host-absolute path (e.g. C:\...) is only meaningful when the
            # runtime *is* this host; it cannot be mapped into WSL.
            return str(Path(configured)) if self.mode == "native" else None
        absolute = (self.repo_root / configured).resolve()
        if self.mode == "native":
            return str(absolute)
        drive = absolute.drive.rstrip(":").lower()
        tail_path = absolute.as_posix().split(":", 1)[-1]
        return f"/mnt/{drive}{tail_path}"


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


def read_result_json(native_dir: Path) -> dict:
    path = native_dir / "result.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


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
    return str(retired)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True, type=Path)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument(
        "--config", type=Path, default=REPO_ROOT / "configs" / "provider.toml"
    )
    parser.add_argument(
        "--cot",
        choices=["full", "melody", "off"],
        default=None,
        help="Override [yue2].cot: symbolic planning mode",
    )
    parser.add_argument("--take-id", type=int, default=None)
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

    extra_tokens, extra_error = split_extra_args(args.extra_arg)
    if extra_error:
        return fail(extra_error)

    session: Path = args.session
    if not session.is_dir():
        return fail(f"session directory does not exist: {session}")
    lyrics_path = session / "lyrics.txt"
    if not lyrics_path.is_file():
        return fail(f"missing {lyrics_path}")

    lyrics = lyrics_path.read_text(encoding="utf-8-sig")
    if not lyrics.strip():
        # Upstream requires lyrics and has no instrumental mode (decision Y9).
        return fail(
            f"{lyrics_path} is empty: YuE2 cannot generate instrumentals (upstream "
            "'lyrics' is a required field with no instrumental mode). Choose the "
            "minimax-music3 model for this session, or write lyrics with section tags."
        )

    style, style_source = read_style(session)
    if not style:
        return fail(
            f"missing style prompt: {session / 'style.txt'} is absent/empty and "
            "caption.json has no inputs.description. compose-brief writes style.txt "
            "(one comma-separated line: language, genre, vocal character, 2-3 "
            "instruments, tempo)."
        )

    if not args.config.is_file():
        return fail(f"config not found: {args.config}")
    try:
        cfg = tomllib.loads(args.config.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        return fail(f"config is not valid TOML: {exc}")
    y = cfg.get("yue2")
    if not y:
        return fail("[yue2] section missing from config")

    take_name = ""
    takes_dir = session / "takes"
    takes_dir.mkdir(parents=True, exist_ok=True)
    if args.take_id is not None:
        take_num = args.take_id
    else:
        existing = [
            int(p.stem.split("-")[1])
            for p in takes_dir.glob("take-*.wav")
            if p.stem.split("-")[1].isdigit()
        ]
        take_num = (max(existing) + 1) if existing else 1
    take_name = f"take-{take_num:02d}"
    wav_path = takes_dir / f"{take_name}.wav"
    flac_path = takes_dir / f"{take_name}.flac"
    meta_path = takes_dir / f"{take_name}.metadata.json"
    request_path = takes_dir / f"{take_name}.request.json"

    cfg_scale = float(y.get("cfg_scale", 0.0) or 0.0)
    cot = args.cot or str(y.get("cot", "full"))
    # Only documented request keys: upstream raises ValueError on unknown fields.
    request: dict[str, object] = {
        "id": take_name,
        "style": style,
        "lyrics": lyrics,
        "cot": cot,
        "seed": args.seed,
    }
    if cfg_scale > 0:
        request["cfg_scale"] = cfg_scale
    request_path.write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")

    # --- runtime + CLI ------------------------------------------------------
    rt = Runtime(y, REPO_ROOT)
    if rt.mode not in ("wsl", "native"):
        return fail(f"unknown [yue2].runtime {rt.mode!r}")
    venv = rt.path(str(y.get("venv_dir", "")))
    if venv is None:
        return fail(
            "cannot resolve [yue2].venv_dir inside the runtime"
            + (" (is WSL installed and running?)" if rt.mode == "wsl" else "")
        )
    cli = f"{venv}/bin/yue2"
    if not rt.bash(f'test -x "{cli}"', timeout=120).ok:
        return fail(
            f"YuE2 is not installed at {cli} - run: python scripts/setup_yue2.py",
            code=2,
        )

    request_rt = rt.path(str(request_path))
    if request_rt is None:
        return fail(f"cannot map {request_path} into the runtime")
    out_dir = takes_dir / f"{take_name}.yue2"
    out_dir_rt = rt.path(str(out_dir))
    if out_dir_rt is None:
        return fail(f"cannot map {out_dir} into the runtime")
    retired = retire_stale_dir(out_dir)

    cmd = [cli, "generate", "--request", request_rt, "--output", out_dir_rt]
    model = str(y.get("model", "") or "").strip()
    if model:
        cmd += ["--model", rt.path(model) or model]
    vae = str(y.get("vae", "") or "").strip()
    if vae:
        cmd += ["--vae", vae]
    if y.get("offline"):
        cmd += ["--offline"]
    cmd += [str(a) for a in (y.get("extra_generate_args") or [])]
    cmd += extra_tokens

    started = time.monotonic()
    res = rt.run(cmd, timeout=CLI_TIMEOUT_S)
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

    # --- provenance snapshots ----------------------------------------------
    for src, suffix in (
        (session / "style.txt", ".style.txt"),
        (session / "caption.md", ".caption.md"),
        (lyrics_path, ".lyrics.txt"),
        (session / "caption.json", ".caption.json"),
    ):
        if src.is_file():
            shutil.copyfile(src, takes_dir / f"{take_name}{suffix}")

    size = wav_path.stat().st_size
    sample_rate, channels = wav_format(wav_path)
    audio_s = size / (sample_rate * channels * 2)  # PCM16
    rtf = round(elapsed / audio_s, 2) if audio_s > 0 else None

    metadata = {
        "schema": "generate_meta/v1",
        "provider": "yue2",
        "take": take_name,
        "endpoint": "local-cli",
        "model": model or "m-a-p/YuE2-3B",
        "vae": vae or "standard",
        "seed": args.seed,
        "cot": cot,
        "cfg_scale": cfg_scale or None,
        "style_source": style_source,
        # Recorded so the frozen request stays honest about model-native overrides.
        "extra_args": extra_tokens or None,
        "truncated": truncated,
        "audio_seconds": result.get("audio_seconds"),
        "sample_rate_hz": sample_rate,
        "channels": channels,
        "bytes": size,
        "elapsed_s": elapsed,
        "started_utc": datetime.now(UTC).isoformat(),
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
    if extra_tokens:
        out["extra_args"] = extra_tokens
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
            sys.stderr.write(f"[generate_yue2] mp3 companion skipped: {tr_out}\n")
            out["mp3"] = None

    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
