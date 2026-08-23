# agentic-music

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Status: experimental pre-scaffold](https://img.shields.io/badge/status-v0.0.0_pre--scaffold-orange)

An agent-executable local music generation studio built around **MiniMax Music 3**: open weights served locally via SGLang-Omni, orchestrated end to end by coding agents such as DeepSeek Harness or Claude Code that follow [AGENTS.md](AGENTS.md) plus a small library of skills instead of improvising commands. Everything runs fully local — no hosted API, no cloud round-trip, no API keys.

> [!WARNING]
> **Early work-in-progress.** This repository is a v0.0.0 pre-scaffold: what you see here describes the system being built toward, not working functionality yet. Layout, scripts, and interfaces may change without notice.

## Requirements

- Windows or Linux host
- NVIDIA CUDA GPU with at least 24 GB of VRAM — a single 24 GB-class GPU is the target configuration (reference hardware: RTX 4090)
- On Windows hosts: WSL2 with a proper Ubuntu distribution (the inference stack runs inside WSL)
- [`uv`](https://docs.astral.sh/uv/) for Python environment and dependency management

## Architecture

The agent drives every stage of the pipeline through deterministic `scripts/` CLIs that emit documented JSON output — never freehand commands:

- **compose-brief** — structured interview with the user; negotiates a creative brief and tagged lyrics.
- **music-caption-rewriter** — expands the brief into a MiniMax Music 3.0 Structured Caption.
- **Local SGLang-Omni server** — serves the MiniMax Music 3 open weights on the local CUDA GPU.
- **generate-song** — produces seeded takes (WAV plus per-take metadata) against the local server.
- **judge-quality** — scores each take on objective audio metrics (duration, LUFS, clipping, trailing silence) plus CLAP text–audio alignment, then ranks the takes.

All per-song state lives in `sessions/<song-id>/` folders (`brief.md`, `lyrics.txt`, `caption.md`, `takes/`, `review.json`) with fixed artifact names, so any agent can resume mid-pipeline by reading the folder alone.

## Project Status

**Phase 0 passed.** MiniMax Music 3 now serves and generates on a **single ≥24 GB-class
GPU** via SGLang-Omni's default two-process topology plus a tuned pipeline config — no
second GPU required. The exact working configuration lives in
[configs/music3-pipeline.yaml](configs/music3-pipeline.yaml), with VRAM measurements and
the decision record in
[plans/2026-08-23-phase0-single-gpu-spike.md](plans/2026-08-23-phase0-single-gpu-spike.md).
The full pipeline (compose → generate → judge) has been validated end to end on one
machine; expect continued churn as docs, packaging, and CI catch up. Implementation
progress against the roadmap is tracked in
[plans/IMPLEMENTATION-STATUS.md](plans/IMPLEMENTATION-STATUS.md).

## Credits & Attribution

- **MiniMax-AI/MiniMax-Music3** — the upstream model repository. Referenced and fetched locally at runtime; its content is not redistributed in this repo (see [NOTICE](NOTICE)).
- **MiniMax skills collection** (including `minimax-music-gen`, MIT licensed) — whose agent-interaction protocol (interview flow, preview-and-confirm, feedback loop) we adapted into our composing skills.
- **CLAP / LAION** — used for text–audio semantic alignment scoring during quality judging.
- This is an independent community project, **not affiliated with or endorsed by MiniMax**.
- MiniMax-Music3 model weights carry their own community license on Hugging Face and must be downloaded separately by each user; they are not included here.

## License

Code in this repository is released under the [MIT License](LICENSE). Third-party components and model weights remain under their own licenses — see [NOTICE](NOTICE).
