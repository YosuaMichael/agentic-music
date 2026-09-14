# agentic-music

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Release](https://img.shields.io/badge/release-v0.0.1-blue)
![Status](https://img.shields.io/badge/status-working%20experimental-orange)

An agent-executable local music generation studio running open-weights models on your own
GPU — currently **YuE2** (default) and **MiniMax Music 3** — orchestrated end to end by
coding agents such as DeepSeek Harness or Claude Code that follow [AGENTS.md](AGENTS.md)
plus five skills, instead of improvising commands. Everything runs fully local: no hosted
API, no cloud round-trip, no API keys.

> [!NOTE]
> Working experimental software (v0.0.1). The full pipeline — interview → prompt →
> seeded takes → quality ranking → browser playback — has been validated end to end with
> MiniMax Music 3, including an owner blind-listening comparison between two inference
> engines. **YuE2 support is new**: the runtime, dispatch and session model choice are
> implemented and unit-tested, but its first end-to-end generation on a target machine is
> still the acceptance test (see
> [plans/2026-09-13-yue2-default-model.md](plans/2026-09-13-yue2-default-model.md) §5).

## Pick a model, once per song

At the start of a song the studio asks **once** which model to use, then records the answer
in that session's `model.json` and never asks again:

| Model | Why | Constraint |
|---|---|---|
| **YuE2** — default | Highest-scoring open model on WildSongBench (SongBench Avg 6.73 vs MiniMax Music 3's 6.28 and Suno v5's 6.87), ~3× faster, ~11 GB VRAM, and it writes an **editable melody + chord score** (`score.abc`) per take | **Vocal songs only**, and its **weights are CC BY-NC 4.0 — non-commercial use only** |
| **MiniMax Music 3** | The previous default engine, ~4 min per song, commercially usable output | **Also vocal songs only** |

> [!IMPORTANT]
> **Neither model can produce an instrumental-only track.** YuE2 requires lyrics and has
> no instrumental mode; MiniMax Music 3 accepts an empty `lyrics.txt` and then sings
> anyway — repeatedly, regardless of how the caption is worded. The studio says this up
> front rather than spending GPU time on it, and flags any such attempt with a `warnings`
> entry. If you specifically need instrumentals, the same audio.cpp runtime exposes other
> `gen` families (`stable_audio`, `ace_step`, `heartmula`) — unverified leads for a future
> feature, not available today. Details:
> [plans/2026-09-14-instrumental-generation-unsupported.md](plans/2026-09-14-instrumental-generation-unsupported.md).

Switching per session is deliberate and reversible (`scripts/select_model.py --force`); the
repo-wide default lives in `configs/provider.toml`.

## Requirements

Depends on which model/runtime you use (see [Architecture](#architecture)):

| Path | GPU VRAM (peak, measured) | Notes |
|---|---|---|
| **Default model — YuE2 (`yue2`)** | ~11 GB (14 GB worst case) | Needs a 24 GB-class GPU + ~24 GB host RAM, PyTorch BF16, and Linux — on Windows it runs in **WSL2**. ~8 GB of weights. No quantization, 48 kHz stereo |
| MiniMax Music 3 — audio.cpp Q8 GGUF | ~14 GB short clips · ~17 GB full songs | 20 GB-class card renders full songs comfortably; 16 GB cards handle short clips |
| Optional — audio.cpp q4 component mix | est. ~12 GB | Trade a little fidelity; switch via `[audiocpp]` component overrides |
| Reference — SGLang-Omni float32+fp8 | ~24 GB | Highest-fidelity fallback; needs WSL2 on Windows |

Both models can be installed side by side and share one GPU, but not at the same time
(YuE2 is one request at a time upstream).

Also required:

- **NVIDIA CUDA GPU with BF16 support** (YuE2 requires BF16 and a 24 GB-class card; the audio.cpp runtime is a Windows CUDA build, and audio.cpp itself also ships Linux/macOS and Vulkan/Metal/CPU backends, untested here)
- **Python 3.12+** — core scripts are stdlib-only; no pip installs needed for generation outside the model runtimes
- **ffmpeg** on PATH — MP3 companions (`transcode.py`) and audio metrics (`analyze_audio.py`)
- [`uv`](https://docs.astral.sh/uv/) — only for the test/lint gates (`ruff`, `pytest`)
- WSL2 + Ubuntu — for **YuE2** and the SGLang reference path, plus the optional CLAP scorer

## Quickstart

This repo is designed to be driven by a coding agent, not by hand. From a harness
session opened in the repository root:

```text
you:  run env-setup
      ← agent audits hardware, installs the runtime for the default model
        (YuE2 in WSL: ~8 GB of weights) and/or the audio.cpp GGUF runtime
        (~19 GB), then smoke-tests generation

you:  I want to create music
      ← agent asks ONCE which model to use (YuE2 by default), interviews you,
        then renders takes
```

Manual equivalent (no agent):

```bash
python scripts/hardware_audit.py          # verify GPU + disk
python scripts/setup_yue2.py              # default model runtime + weights (idempotent)
python scripts/setup_audiocpp.py          # optional: MiniMax Music 3 runtime + weights
python scripts/select_model.py --session studio/sessions/<your-id>   # ask-once state
python scripts/generate_take.py \
    --session studio/sessions/<your-id> --seed 7
```

Songs live in `studio/sessions/<song-id>/` — `brief.md`, `lyrics.txt`, `style.txt`
(YuE2's prompt), `caption.md` (Music 3's prompt), `model.json` (the model chosen for
that song), `takes/*.wav` masters plus `.mp3` companions, and `review.json` when
judged. YuE2 takes also keep their upstream artifacts, including the editable
`score.abc`. Point any static file server at that folder (or use
[`scripts/serve_artifacts.py`](scripts/serve_artifacts.py), which adds per-take player
pages) to listen from any device.

### Review the composition before paying for the audio (YuE2)

YuE2 writes an editable melody-and-chord score *before* it renders. Because that plan is
the creative decision — and there is no length knob to fall back on — the default YuE2
flow shows it to you first:

```bash
# 1. plan only: a symbolic score, no audio (~19 s)   -> plan/v1
python scripts/generate_take.py --session studio/sessions/<your-id> --seed 7 --stage plan

# 2. render the approved composition (~43 s); seed and cot come from the plan
python scripts/generate_take.py --session studio/sessions/<your-id> \
    --from-plan studio/sessions/<your-id>/plans/plan-01

# 2b. edit a copy of the score and render that instead
python scripts/generate_take.py --session studio/sessions/<your-id> \
    --from-plan studio/sessions/<your-id>/plans/plan-01 \
    --score-file studio/sessions/<your-id>/plans/plan-01.edited.abc
```

Plans live in their own `plans/plan-NN/` namespace (no audio, and planning never consumes
a take id), and every rendered take records `rendered_from` — the plan, the score's
SHA-256, and whether you edited it — so a take traces back to the exact composition it
realised. Approving a plan unchanged reproduces the one-shot song **byte-identically**;
measurements and the plan file layout are in
[plans/2026-09-14-yue2-score-first-workflow.md](plans/2026-09-14-yue2-score-first-workflow.md).

## Architecture

Two agent workspaces, one pipeline:

- **`studio/`** — the creation context. A lean `AGENTS.md` tells the agent to start
  composing immediately, ask how many takes you want, report duration/wall-time per
  take, and never run quality judging without asking first. Mistakes and user feedback
  are recorded in `studio/learnings/` (gitignored, per-machine), which every skill
  consults before acting — the studio gets better the more you use it.
- **Repository root** — development context: decision history in
  [`plans/`](plans/INDEX.md), deterministic JSON-out `scripts/`, and the five skills in
  [`.dsh/skills/`](.dsh/skills/) (a DeepSeek Harness-native discovery root) — including
  **model-guide**, the per-model parameter and capability reference.

Pipeline: **compose-brief** (choose model once → brief + tagged lyrics + `style.txt` +
Structured Caption) → **generate-song** (`scripts/generate_take.py` routes to the
session's model) → **judge-quality** (optional; objective metrics + CLAP alignment,
ranked verdict).

[`configs/provider.toml`](configs/provider.toml) holds two orthogonal axes: the
**model** (`[models].default = "yue2"`, overridden per session in `model.json`) and,
for MiniMax Music 3 only, the **engine** (`[provider].type = "audiocpp"` — pure-C++
ggml, all-Q8 components — or `"local"` — SGLang-Omni server, float32 synthesis + fp8
backbone).

Performance snapshot (single RTX 4090, first **measured** end-to-end numbers, 2026-09-13):
**YuE2 rendered a 107.8 s song in 45.5 s of model time (RTF 0.42) — 54.7 s end to end
through the pipeline — at ~9.3 GiB peak.** Stage detail and methodology:
[plans/2026-09-13-yue2-default-model.md](plans/2026-09-13-yue2-default-model.md) §5.1 and
the `model-guide` skill. For comparison, MiniMax Music 3 on this machine: audio.cpp Q8
≈ 4 min for a ~200 s song at 16.8 GB peak; SGLang ≈ 16–19 min at 23.6 GB
([plans/2026-08-23-performance-research.md](plans/2026-08-23-performance-research.md)).
Two caveats worth knowing up front: YuE2 generation must run **offline** after setup
(online revalidation cost 5.5× the whole take), and identical seeds reproduce
byte-identical audio.

## Project Status

v0.0.1 released; both MiniMax Music 3 inference paths validated end to end and confirmed
by owner listening. YuE2 was added 2026-09-13 as the **default model** (session-scoped
choice, asked once) — its runtime, dispatch and guards are implemented and tested, and its
first end-to-end generation is the outstanding acceptance test. Roadmap: CI workflow,
packaging polish — progress tracked in
[plans/IMPLEMENTATION-STATUS.md](plans/IMPLEMENTATION-STATUS.md).

## Credits & Attribution

- **YuE2** ([multimodal-art-projection/YuE](https://github.com/multimodal-art-projection/YuE), [m-a-p/YuE2-3B](https://huggingface.co/m-a-p/YuE2-3B)) — the default music model. Referenced and fetched locally at runtime (`scripts/setup_yue2.py` installs from the pinned checkout); nothing from it is redistributed here. Its first-party code is Apache-2.0; **its model weights are CC BY-NC 4.0 — non-commercial use only**, so YuE2 output cannot be used commercially without separate terms.
- **MiniMax-AI/MiniMax-Music3** — the upstream model repository. Referenced and fetched locally at runtime; its content is not redistributed in this repo (see [NOTICE](NOTICE)).
- **MiniMax skills collection** (including `minimax-music-gen`, MIT licensed) — whose agent-interaction protocol (interview flow, preview-and-confirm, feedback loop) we adapted into our composing skills.
- **[audio.cpp](https://github.com/0xShug0/audio.cpp)** (Apache-2.0) — the C++/ggml runtime behind the MiniMax Music 3 audio.cpp engine, and **[audio-cpp/MiniMax-Music3-GGUF](https://huggingface.co/audio-cpp/MiniMax-Music3-GGUF)** — the community quantization used here.
- **CLAP / LAION** — used for text–audio semantic alignment scoring during quality judging.
- This is an independent community project, **not affiliated with or endorsed by** MiniMax or the YuE2 authors.
- Model weights are **not included here**: each model's weights carry their own license on Hugging Face and must be downloaded separately by each user.

## License

Code in this repository is released under the [MIT License](LICENSE). Third-party components and model weights remain under their own licenses — see [NOTICE](NOTICE).
