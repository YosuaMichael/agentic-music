#!/usr/bin/env python3
"""Transcode generated WAV takes to MP3 companions (ffmpeg + libmp3lame).

Usage:
    python scripts/transcode.py --audio studio/sessions/<id>/takes/take-01.wav [--quality 2]
    python scripts/transcode.py --session studio/sessions/<id> [--quality 2]

Writes `<stem>.mp3` next to each input (master WAV is never touched). Uses
ffmpeg's libmp3lame encoder in VBR mode (`-qscale:a`, 0=best .. 9=worst;
default 2 ≈ ~190 kbps transparent).

JSON contract (stdout) — transcode/v1:
    {"schema": "transcode/v1", "ok": true, "outputs": [{"wav": ..., "mp3": ...,
     "bytes": N}], "error": null}
Exit codes: 0 success; 2 bad inputs; 8 ffmpeg missing/failed.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def fail(message: str, code: int = 2) -> int:
    print(json.dumps({"schema": "transcode/v1", "ok": False, "outputs": [], "error": message}))
    return code


def encode(wav: Path, quality: int) -> Path:
    mp3 = wav.with_suffix(".mp3")
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(wav),
        "-codec:a", "libmp3lame",
        "-qscale:a", str(quality),
        str(mp3),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg rc={proc.returncode}: {proc.stderr[-400:]}")
    return mp3


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--audio", type=Path, help="Single WAV to transcode")
    group.add_argument("--session", type=Path, help="Session dir: sweep takes/*.wav")
    parser.add_argument("--quality", type=int, default=2, help="LAME VBR 0..9 (default 2)")
    args = parser.parse_args()

    if shutil.which("ffmpeg") is None:
        return fail("ffmpeg not found on PATH (install via: winget install Gyan.FFmpeg)", 8)

    wavs: list[Path]
    if args.audio is not None:
        if args.audio.suffix.lower() != ".wav" or not args.audio.is_file():
            return fail(f"not a WAV file: {args.audio}")
        wavs = [args.audio]
    else:
        takes = args.session / "takes"
        if not takes.is_dir():
            return fail(f"no takes directory under {args.session}")
        wavs = sorted(
            p for p in takes.glob("*.wav") if not p.stem.endswith("_failed")
        )
        if not wavs:
            return fail(f"no WAV takes found under {takes}")

    outputs = []
    try:
        for wav in wavs:
            mp3 = encode(wav, args.quality)
            outputs.append({"wav": str(wav), "mp3": str(mp3), "bytes": mp3.stat().st_size})
    except Exception as exc:  # noqa: BLE001 - report any encode failure
        return fail(str(exc), 8)

    print(json.dumps({"schema": "transcode/v1", "ok": True, "outputs": outputs, "error": None}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
