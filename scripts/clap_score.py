#!/usr/bin/env python3
"""CLAP text-audio semantic alignment score for one take (best effort).

Usage (run INSIDE the WSL venv — needs torch/transformers):
    /root/agentic-music-venv/bin/python scripts/clap_score.py \
        --caption studio/sessions/<id>/caption.md --audio studio/sessions/<id>/takes/take-01.wav

Downloads laion/clap-htsat-fused (~2 GB) on first use, cached afterwards.
If CLAP dependencies are unavailable, returns ok=false with reason so the
judge-quality skill can proceed with metrics-only scoring (decision D4).

JSON contract (stdout):

    clap_score/v1
    {
      "schema": "clap_score/v1",
      "caption": "<path>",
      "audio": "<path>",
      "similarity": 0.31|null,          // cosine similarity, typically 0..1
      "model": "laion/clap-htsat-fused"|null,
      "ok": true|false,
      "error": null|"reason CLAP unavailable"
    }
"""

from __future__ import annotations

import argparse
import json
import sys


def fail(reason: str) -> int:
    print(
        json.dumps(
            {
                "schema": "clap_score/v1",
                "caption": None,
                "audio": None,
                "similarity": None,
                "model": None,
                "ok": False,
                "error": reason,
            }
        )
    )
    return 0  # unavailable != pipeline failure; judge proceeds metrics-only


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--caption", required=True)
    parser.add_argument("--audio", required=True)
    args = parser.parse_args()

    try:
        import numpy as np  # noqa: F401 - dependency probe
        import torch
        import transformers  # type: ignore # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return fail(f"CLAP dependencies unavailable: {exc.__class__.__name__}: {exc}")

    caption_text = open(args.caption, encoding="utf-8").read()
    # Caption markdown may contain headers; feed plain prose lines only.
    prose = " ".join(
        line.strip().lstrip("-*# ").strip()
        for line in caption_text.splitlines()
        if line.strip() and not line.strip().startswith(("#", "|"))
    )[:1500]  # stay well under CLAP's 512-token text window

    model_id = "laion/clap-htsat-fused"
    try:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        from transformers import ClapModel, ClapProcessor  # type: ignore

        processor = ClapProcessor.from_pretrained(model_id)
        model = ClapModel.from_pretrained(model_id).to(device).eval()

        # Decode with librosa/soundfile: avoids torchcodec's FFmpeg shared-lib
        # requirement, and resamples 32 kHz model output to CLAP's 48 kHz.
        import librosa

        waveform, _ = librosa.load(args.audio, sr=48000, mono=True)
        inputs = processor(
            text=[prose], audio=waveform, return_tensors="pt", sampling_rate=48000
        )
        inputs = {k: v.to(device) for k, v in inputs.items()}
        with torch.no_grad():
            outputs = model(**inputs)
        sim = torch.cosine_similarity(outputs.audio_embeds, outputs.text_embeds).item()
        sim = round(float(max(0.0, min(1.0, (sim + 1) / 2))), 4)  # map [-1,1]->[0,1]
        print(
            json.dumps(
                {
                    "schema": "clap_score/v1",
                    "caption": args.caption,
                    "audio": args.audio,
                    "similarity": sim,
                    "model": model_id,
                    "ok": True,
                    "error": None,
                }
            )
        )
        return 0
    except Exception as exc:  # noqa: BLE001
        return fail(f"CLAP inference failed: {exc.__class__.__name__}: {exc}")


if __name__ == "__main__":
    sys.exit(main())
