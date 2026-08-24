# agentic-music

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Release](https://img.shields.io/badge/release-v0.0.1-blue)
![Status](https://img.shields.io/badge/status-working%20experimental-orange)

An agent-executable local music generation studio built around **MiniMax Music 3**: open
weights running quantized on your own GPU, orchestrated end to end by coding agents such
as DeepSeek Harness or Claude Code that follow [AGENTS.md](AGENTS.md) plus four skills —
instead of improvising commands. Everything runs fully local: no hosted API, no cloud
round-trip, no API keys.

> [!NOTE]
> Working experimental software (v0.0.1). The full pipeline — interview → caption →
> seeded takes → quality ranking → browser playback — has been validated end to end,
> including an owner blind-listening comparison between the two inference engines.

## Requirements

Depends on which inference path you use (see [Architecture](#architecture)):

| Path | GPU VRAM (peak, measured) | Notes |
|---|---|---|
| **Default — audio.cpp Q8 GGUF** | ~14 GB short clips · ~17 GB full songs | 20 GB-class card renders full songs comfortably; 16 GB cards handle short clips |
| Optional — audio.cpp q4 component mix | est. ~12 GB | Trade a little fidelity; switch via `[audiocpp]` component overrides |
| Reference — SGLang-Omni float32+fp8 | ~24 GB | Highest-fidelity fallback; needs WSL2 on Windows |

Also required:

- **NVIDIA CUDA GPU** (the pinned runtime is a Windows CUDA build; audio.cpp itself also ships Linux/macOS and Vulkan/Metal/CPU backends, untested here)
- **Python 3.12+** — core scripts are stdlib-only; no pip installs needed for generation
- **ffmpeg** on PATH — MP3 companions (`transcode.py`) and audio metrics (`analyze_audio.py`)
- [`uv`](https://docs.astral.sh/uv/) — only for the test/lint gates (`ruff`, `pytest`)
- WSL2 + Ubuntu — **only** for the SGLang reference path and the optional CLAP scorer

## Quickstart

This repo is designed to be driven by a coding agent, not by hand. From a harness
session opened in the repository root:

```text
you:  run env-setup
      ← agent audits hardware, installs the audio.cpp runtime, downloads
        ~19 GB of Q8 model components, and smoke-tests generation

you:  I want to create music
      ← agent starts the compose-brief interview, then renders takes
```

Manual equivalent (no agent):

```bash
python scripts/hardware_audit.py          # verify GPU + disk
python scripts/setup_audiocpp.py          # install runtime + weights (idempotent)
python scripts/generate_audiocpp.py \
    --session studio/sessions/<your-id> --seed 7 --duration-sec 30
```

Songs live in `studio/sessions/<song-id>/` — `brief.md`, `lyrics.txt`,
`caption.md`, tagged `lyrics.txt` inputs, `takes/*.wav` masters plus `.mp3`
companions, and `review.json` when judged. Point any static file server at that
folder (or use [`scripts/serve_artifacts.py`](scripts/serve_artifacts.py), which adds
per-take player pages) to listen from any device.

## Architecture

Two agent workspaces, one pipeline:

- **`studio/`** — the creation context. A lean `AGENTS.md` tells the agent to start
  composing immediately, ask how many takes you want, report duration/wall-time per
  take, and never run quality judging without asking first. Mistakes and user feedback
  are recorded in `studio/learnings/` (gitignored, per-machine), which every skill
  consults before acting — the studio gets better the more you use it.
- **Repository root** — development context: decision history in
  [`plans/`](plans/INDEX.md), deterministic JSON-out `scripts/`, and the four skills in
  [`.dsh/skills/`](.dsh/skills/) (a DeepSeek Harness-native discovery root).

Pipeline: **compose-brief** (interview → brief + tagged lyrics + Structured Caption) →
**generate-song** (seeded takes via the configured provider) → **judge-quality**
(optional; objective metrics + CLAP alignment, ranked verdict).

Providers are switched in [`configs/provider.toml`](configs/provider.toml):
`type = "audiocpp"` (default; pure-C++ ggml runtime, all-Q8 components) or
`type = "local"` (SGLang-Omni server, float32 synthesis + fp8 backbone).

Performance snapshot (single RTX 4090, ~200 s song): audio.cpp Q8 ≈ **4 min**, SGLang
≈ 16–19 min; peak VRAM 16.8 GB vs 23.6 GB. Measurements and rejected experiments live in
[plans/2026-08-23-performance-research.md](plans/2026-08-23-performance-research.md).

## Project Status

v0.0.1 released. Both inference paths validated end to end; audio.cpp Q8 confirmed by
owner listening against the SGLang reference. Roadmap: CI workflow, packaging polish —
progress tracked in
[plans/IMPLEMENTATION-STATUS.md](plans/IMPLEMENTATION-STATUS.md).

## Credits & Attribution

- **MiniMax-AI/MiniMax-Music3** — the upstream model repository. Referenced and fetched locally at runtime; its content is not redistributed in this repo (see [NOTICE](NOTICE)).
- **MiniMax skills collection** (including `minimax-music-gen`, MIT licensed) — whose agent-interaction protocol (interview flow, preview-and-confirm, feedback loop) we adapted into our composing skills.
- **[audio.cpp](https://github.com/0xShug0/audio.cpp)** (Apache-2.0) — the C++/ggml runtime behind the default provider, and **[audio-cpp/MiniMax-Music3-GGUF](https://huggingface.co/audio-cpp/MiniMax-Music3-GGUF)** — the community quantization used here.
- **CLAP / LAION** — used for text–audio semantic alignment scoring during quality judging.
- This is an independent community project, **not affiliated with or endorsed by MiniMax**.
- MiniMax-Music3 model weights carry their own community license on Hugging Face and must be downloaded separately by each user; they are not included here.

## License

Code in this repository is released under the [MIT License](LICENSE). Third-party components and model weights remain under their own licenses — see [NOTICE](NOTICE).
