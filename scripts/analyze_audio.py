#!/usr/bin/env python3
"""Objective audio metrics for one generated take.

Usage:
    python scripts/analyze_audio.py --audio sessions/<id>/takes/take-01.wav

Wraps ffprobe/ffmpeg (must be on PATH). Stdlib-only otherwise.

JSON contract (stdout):

    analyze_audio/v1
    {
      "schema": "analyze_audio/v1",
      "audio": "<path>",
      "duration_s": 183.2,
      "sample_rate_hz": 32000,
      "channels": 2,
      "peak_dbfs": -1.2,
      "mean_volume_dbfs": -18.4,
      "integrated_lufs": -14.1|null,
      "trailing_silence_s": 0.8,
      "ok": true,
      "error": null
    }
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys


def _run(cmd: list[str], timeout: int = 300) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    return proc.stdout + "\n" + proc.stderr


def fail(message: str) -> int:
    print(json.dumps({"schema": "analyze_audio/v1", "ok": False, "error": message}))
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", required=True)
    args = parser.parse_args()
    path = args.audio

    # --- container/stream facts -------------------------------------------------
    out = _run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", path]
    )
    try:
        probe = json.loads(out)
        fmt = probe["format"]
        duration = float(fmt["duration"])
        stream = next(s for s in probe["streams"] if s.get("codec_type") == "audio")
        sample_rate = int(stream["sample_rate"])
        channels = int(stream["channels"])
    except Exception as exc:  # noqa: BLE001 - report anything unexpected as failure
        return fail(f"ffprobe failed: {exc}")

    # --- loudness / peaks ---------------------------------------------------------
    vol = _run(["ffmpeg", "-hide_banner", "-i", path, "-af", "volumedetect", "-f", "null", "-"])

    def grab(pattern: str) -> float | None:
        m = re.search(pattern, vol)
        return float(m.group(1)) if m else None

    peak = grab(r"max_volume:\s*(-?[0-9.]+)\s*dB")
    mean_volume = grab(r"mean_volume:\s*(-?[0-9.]+)\s*dB")

    lufs: float | None = None
    ln = _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            path,
            "-af",
            "loudnorm=print_format=json",
            "-f",
            "null",
            "-",
        ]
    )
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", ln, re.DOTALL)
    if m:
        try:
            lufs = float(json.loads(m.group(0))["input_i"])
        except (ValueError, KeyError):
            pass

    # --- trailing silence -----------------------------------------------------------
    sil = _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            path,
            "-af",
            "silencedetect=noise=-50dB:d=0.5",
            "-f",
            "null",
            "-",
        ]
    )
    starts = [float(x) for x in re.findall(r"silence_start:\s*(-?[0-9.]+)", sil)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*(-?[0-9.]+)", sil)]
    trailing = 0.0
    if len(starts) > len(ends):  # file ends inside a silence span
        trailing = max(0.0, min(duration, duration) - max(0.0, starts[-1]))
    elif starts and ends and abs(ends[-1] - duration) < 0.25:
        trailing = max(0.0, ends[-1] - starts[-1])

    print(
        json.dumps(
            {
                "schema": "analyze_audio/v1",
                "audio": path,
                "duration_s": round(duration, 2),
                "sample_rate_hz": sample_rate,
                "channels": channels,
                "peak_dbfs": peak,
                "mean_volume_dbfs": mean_volume,
                "integrated_lufs": lufs,
                "trailing_silence_s": round(trailing, 2),
                "ok": True,
                "error": None,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
