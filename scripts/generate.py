#!/usr/bin/env python3
"""Generate one seeded music take against the configured provider endpoint.

Usage:
    python scripts/generate.py --session sessions/<song-id> --seed 7 \
                               [--config configs/provider.toml]

Reads caption.md (instructions) and lyrics.txt (input) from the session dir,
POSTs to the shared speech API served by SGLang-Omni, and writes:

    sessions/<song-id>/takes/take-NN.wav
    sessions/<song-id>/takes/take-NN.metadata.json

Stdlib-only (urllib + tomllib): runs identically on the Windows host and in
WSL. Long-running; invoke as a background job from skills.

JSON contract (stdout):

    generate/v1
    {
      "schema": "generate/v1",
      "ok": true|false,
      "take": "take-01"|null,
      "wav": "sessions/.../takes/take-01.wav"|null,
      "metadata": "sessions/.../takes/take-01.metadata.json"|null,
      "bytes": 1048576|null,
      "elapsed_s": 321.4|null,
      "error": null|"..."
    }

Exit codes: 0 success; 2 bad inputs; 3 HTTP error from server; 4 timeout;
5 connection failure.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import tomllib
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

HTTP_TIMEOUT_S = 3600


def fail(code: int, message: str) -> int:
    print(json.dumps({"schema": "generate/v1", "ok": False, "error": message}))
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True, type=Path)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "configs" / "provider.toml",
    )
    parser.add_argument(
        "--max-new-tokens",
        type=int,
        default=None,
        help="Override [generation].max_new_tokens (spike/smoke tests)",
    )
    parser.add_argument(
        "--take-id",
        type=int,
        default=None,
        help="Explicit take number (for concurrent dispatch — avoids numbering races)",
    )
    args = parser.parse_args()

    session: Path = args.session
    caption_path = session / "caption.md"
    lyrics_path = session / "lyrics.txt"
    if not caption_path.is_file():
        return fail(2, f"missing {caption_path}")
    if not lyrics_path.is_file():
        return fail(2, f"missing {lyrics_path}")

    cfg = tomllib.loads(args.config.read_text(encoding="utf-8"))
    local, gen = cfg["local"], cfg["generation"]
    url = f"http://{local['host']}:{local['port']}/v1/audio/speech"

    max_new_tokens = (
        args.max_new_tokens
        if args.max_new_tokens is not None
        else gen.get("max_new_tokens", 9000)
    )
    payload = {
        "model": local["model"],
        "input": lyrics_path.read_text(encoding="utf-8"),
        "instructions": caption_path.read_text(encoding="utf-8"),
        "response_format": gen.get("response_format", "wav"),
        "seed": args.seed,
        "max_new_tokens": max_new_tokens,
        "stream": False,
    }

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

    started = time.monotonic()
    try:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_S) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        return fail(3, f"HTTP {exc.code}: {exc.read()[:400]!r}")
    except TimeoutError:
        return fail(4, f"timed out after {HTTP_TIMEOUT_S}s")
    except urllib.error.URLError as exc:
        return fail(5, f"connection failed: {exc.reason}")

    elapsed = round(time.monotonic() - started, 1)
    wav_path.write_bytes(body)

    metadata = {
        "schema": "generate_meta/v1",
        "take": take_name,
        "endpoint": url,
        "model": payload["model"],
        "seed": args.seed,
        "max_new_tokens": payload["max_new_tokens"],
        "bytes": len(body),
        "elapsed_s": elapsed,
        "started_utc": datetime.now(UTC).isoformat(),
    }
    meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "schema": "generate/v1",
                "ok": True,
                "take": take_name,
                "wav": str(wav_path),
                "metadata": str(meta_path),
                "bytes": len(body),
                "elapsed_s": elapsed,
                "error": None,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
