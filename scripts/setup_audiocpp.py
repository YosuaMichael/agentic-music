#!/usr/bin/env python3
"""Set up the audio.cpp GGUF provider: runtime binaries, model GGUFs, Q8 dir.

Usage:
    python scripts/setup_audiocpp.py [--config configs/provider.toml] [--force]

Idempotent:
1. Ensures `.tools/audiocpp/audiocpp_cli.exe` exists (downloads + extracts the
   pinned audio.cpp Windows CUDA build and its CUDA runtime pack otherwise).
2. Ensures every model file listed under `[audiocpp].hf_files` exists with a
   plausible size (downloads missing ones from `[audiocpp].hf_repo`).
3. Assembles the all-Q8 hardlink directory (`[audiocpp].model_dir`) where the
   Q8 language-model / flow-transformer GGUFs appear under the default package
   filenames (release 0.6.1 requires default names to exist before it will
   load anything; see plans/2026-08-23-audiocpp-gguf-provider.md).

JSON contract (stdout) — setup_audiocpp/v1:
    {"schema": "setup_audiocpp/v1", "ok": true, "actions": [...],
     "skipped": [...], "error": null}
Exit codes: 0 success; 2 bad inputs/config; 8 download/extraction failure.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def emit(ok: bool, actions: list[str], skipped: list[str], error: str | None) -> int:
    print(
        json.dumps(
            {
                "schema": "setup_audiocpp/v1",
                "ok": ok,
                "actions": actions,
                "skipped": skipped,
                "error": error,
            },
            indent=2,
        )
    )
    return 0 if ok else 8


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=7200) as resp, tmp.open("wb") as fh:
        while chunk := resp.read(1 << 20):
            fh.write(chunk)
    tmp.replace(dest)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=REPO_ROOT / "configs" / "provider.toml")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download binaries and rebuild the hardlink directory",
    )
    args = parser.parse_args()

    cfg = tomllib.loads(args.config.read_text(encoding="utf-8"))
    ac = cfg.get("audiocpp")
    if not ac:
        return emit(False, [], [], "[audiocpp] section missing from config")

    tools_dir = REPO_ROOT / ".tools" / "audiocpp"
    cli_exe = REPO_ROOT / ac["cli_path"]
    actions: list[str] = []
    skipped: list[str] = []

    # 1. Runtime binaries -----------------------------------------------------
    if cli_exe.is_file() and not args.force:
        skipped.append(f"cli binaries present: {cli_exe}")
    else:
        try:
            for key in ("release_zip_cli", "release_zip_runtime"):
                url, name = ac[key], ac[key].rsplit("/", 1)[-1]
                zpath = tools_dir / name
                if not zpath.is_file():
                    actions.append(f"download {name}")
                    download(url, zpath)
                actions.append(f"extract {name}")
                with zipfile.ZipFile(zpath) as zf:
                    zf.extractall(tools_dir)
                zpath.unlink()
        except Exception as exc:  # noqa: BLE001 - report any fetch failure
            return emit(False, actions, skipped, f"binary setup failed: {exc}")
        if not cli_exe.is_file():
            return emit(False, actions, skipped, f"CLI still missing after extract: {cli_exe}")

    # 2. Model GGUFs ----------------------------------------------------------
    model_dir = REPO_ROOT / ac["model_dir"]
    src_dir = REPO_ROOT / ac.get("hf_dir", "models/audiocpp/MiniMax-Music3-GGUF")
    base = f"https://huggingface.co/{ac['hf_repo']}/resolve/main"
    try:
        for rel in ac["hf_files"]:
            dest = src_dir / rel
            if dest.is_file() and dest.stat().st_size > 1_000_000 and not args.force:
                skipped.append(f"model file present: {rel}")
                continue
            if dest.name.endswith(".json") or "/" in rel:
                if dest.is_file() and dest.stat().st_size > 0 and not args.force:
                    skipped.append(f"model file present: {rel}")
                    continue
            actions.append(f"download {rel}")
            download(f"{base}/{rel.replace(chr(92), '/')}", dest)
    except Exception as exc:  # noqa: BLE001
        return emit(False, actions, skipped, f"model download failed: {exc}")

    # 3. All-Q8 hardlink directory --------------------------------------------
    pairs = [
        ("condition_encoder.gguf", "condition_encoder.gguf"),
        ("vocoder.gguf", "vocoder.gguf"),
        ("rvq_depth_decoder_q8_0.gguf", "rvq_depth_decoder_q8_0.gguf"),
        ("language_model_q8_0.gguf", "language_model_q4_0.gguf"),
        ("transformer_q8_0.gguf", "transformer_q4_0.gguf"),
    ]
    copies = ["config.json"] + [
        p
        for p in (
            "config/language_model.json",
            "config/rvq_depth_decoder.json",
            "config/condition_encoder.json",
            "config/transformer.json",
            "config/vocoder.json",
            "tokenizer/tokenizer.json",
            "tokenizer/tokenizer_config.json",
        )
    ]
    if model_dir.exists() and not args.force:
        skipped.append(f"hardlink dir present: {model_dir}")
    else:
        model_dir.mkdir(parents=True, exist_ok=True)
        for rel in copies:
            dst = model_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            src = src_dir / rel
            if not src.is_file():
                return emit(False, actions, skipped, f"missing source for copy: {src}")
            if dst.resolve() != src.resolve():
                dst.write_bytes(src.read_bytes())
        actions.append("copied configs/tokenizer into hardlink dir")
        for src_name, dst_name in pairs:
            src, dst = src_dir / src_name, model_dir / dst_name
            if not src.is_file():
                return emit(False, actions, skipped, f"missing source for link: {src}")
            if dst.is_file():
                dst.unlink()
            try:
                subprocess.run(
                    ["cmd", "/c", "mklink", "/H", str(dst), str(src)],
                    check=True,
                    capture_output=True,
                )
            except subprocess.CalledProcessError:
                dst.write_bytes(src.read_bytes())  # fallback: real copy
        actions.append(f"hardlinked Q8 GGUFs into {model_dir.name}")

    return emit(True, actions, skipped, None)


if __name__ == "__main__":
    sys.exit(main())
