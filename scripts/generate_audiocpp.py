#!/usr/bin/env python3
"""Generate one seeded take via the audio.cpp GGUF runtime (alternative provider).

Usage:
    python scripts/generate_audiocpp.py --session sessions/<song-id> --seed 7 \
        [--duration-sec 360] [--take-id N] [--config configs/provider.toml]

Reads caption.md (--text) and lyrics.txt (--request-option lyrics=...) from the
session dir, invokes audiocpp_cli.exe --task gen --family minimax_music3, and
writes the same session artifacts as scripts/generate.py:

    sessions/<song-id>/takes/take-NN.wav
    sessions/<song-id>/takes/take-NN.metadata.json

duration-sec maps 1:1 to the AR frame budget (25 frames/second), matching
max_new_tokens semantics on the SGLang provider (9000 frames = 360 s).

JSON contract (stdout) — generate/v1, identical shape to scripts/generate.py,
with two additive fields ("provider": "audiocpp", "rtf": float|null).
Adding optional keys is non-breaking under our schema policy.

Exit codes: 0 success; 2 bad inputs; 8 CLI execution failure.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import tomllib
from datetime import UTC, datetime
from pathlib import Path


def fail(message: str) -> int:
    print(json.dumps({"schema": "generate/v1", "ok": False, "error": message}))
    return 2


def windows_to_cli(path: Path) -> str:
    return str(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True, type=Path)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "configs" / "provider.toml",
    )
    parser.add_argument("--duration-sec", type=int, default=None)
    parser.add_argument("--take-id", type=int, default=None)
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=None,
        help="Override [audiocpp].model_dir (component-mix A/B tests)",
    )
    args = parser.parse_args()

    session: Path = args.session
    caption_path = session / "caption.md"
    lyrics_path = session / "lyrics.txt"
    if not caption_path.is_file():
        return fail(f"missing {caption_path}")
    if not lyrics_path.is_file():
        return fail(f"missing {lyrics_path}")

    cfg = tomllib.loads(args.config.read_text(encoding="utf-8"))
    ac, gen = cfg["audiocpp"], cfg["generation"]
    repo_root = args.config.resolve().parent.parent
    cli = repo_root / ac["cli_path"]
    model_dir = args.model_dir if args.model_dir else repo_root / ac["model_dir"]
    if not cli.is_file():
        return fail(f"audio.cpp CLI not found: {cli}")

    duration_sec = (
        args.duration_sec
        if args.duration_sec is not None
        else round(gen.get("max_new_tokens", 9000) / 25)
    )

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
    meta_path = takes_dir / f"{take_name}.metadata.json"

    lyrics = lyrics_path.read_text(encoding="utf-8")
    cmd = [
        str(cli),
        "--task", "gen",
        "--family", ac["family"],
        "--model", str(model_dir),
        "--backend", ac["backend"],
        "--text", caption_path.read_text(encoding="utf-8"),
        "--request-option", f"lyrics={lyrics}",
        "--request-option", f"duration_sec={duration_sec}",
        "--request-option", f"num_inference_steps={ac['num_inference_steps']}",
        "--request-option", f"guidance_scale={ac['guidance_scale']}",
        "--request-option", f"ar_guidance_scale={ac['ar_guidance_scale']}",
        "--request-option", f"top_k={ac['top_k']}",
        "--request-option", f"seed={args.seed}",
    ]
    # Optional component overrides (release 0.6.1 only honors them when the
    # named files exist; the default package names must be present regardless).
    for key in ("language_model_gguf", "rvq_depth_decoder_gguf", "flow_transformer_gguf"):
        if key in ac:
            cmd += ["--session-option", f"{ac['family']}.{key}={ac[key]}"]
    cmd += [
        "--out", str(wav_path),
        "--metrics",
    ]

    started = time.monotonic()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
    except subprocess.TimeoutExpired:
        print(
            json.dumps(
                {"schema": "generate/v1", "ok": False, "error": "CLI timed out after 7200s"}
            )
        )
        return 8
    elapsed = round(time.monotonic() - started, 1)

    metrics_tail = "\n".join((proc.stdout or "").splitlines()[-12:])
    err_tail = "\n".join((proc.stderr or "").splitlines()[-30:])
    if proc.returncode != 0 or not wav_path.is_file():
        sys.stderr.write(
            f"[generate_audiocpp] CLI failed rc={proc.returncode}\n"
            f"--- stdout tail ---\n{metrics_tail}\n--- stderr tail ---\n{err_tail}\n"
        )
        print(
            json.dumps(
                {
                    "schema": "generate/v1",
                    "ok": False,
                    "error": f"audiocpp CLI rc={proc.returncode} (see stderr tail)",
                }
            )
        )
        return 8

    size = wav_path.stat().st_size
    # Read true format from the WAV header (audio.cpp emits 44.1 kHz stereo,
    # upstream Python emits 32 kHz — never assume).
    import struct

    with wav_path.open("rb") as fh:
        header = fh.read(44)
    if header[:4] != b"RIFF" or header[8:12] != b"WAVE":
        return fail("CLI produced a file that is not a RIFF/WAVE WAV")
    _channels, sample_rate = struct.unpack("<HI", header[22:28])
    bytes_per_sample = 2  # PCM16
    audio_s = size / (sample_rate * _channels * bytes_per_sample)
    metadata = {
        "schema": "generate_meta/v1",
        "provider": "audiocpp",
        "take": take_name,
        "endpoint": "local-cli",
        "model": ac["family"] + " (GGUF q8)",
        "seed": args.seed,
        "duration_sec_budget": duration_sec,
        "num_inference_steps": ac["num_inference_steps"],
        "bytes": size,
        "elapsed_s": elapsed,
        "started_utc": datetime.now(UTC).isoformat(),
    }
    meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    rtf = round(elapsed / audio_s, 2) if audio_s > 0 else None
    print(
        json.dumps(
            {
                "schema": "generate/v1",
                "ok": True,
                "provider": "audiocpp",
                "rtf": rtf,
                "take": take_name,
                "wav": str(wav_path),
                "metadata": str(meta_path),
                "bytes": size,
                "elapsed_s": elapsed,
                "error": None,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
