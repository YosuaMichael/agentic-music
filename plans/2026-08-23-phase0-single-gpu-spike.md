# Phase 0 — Single-GPU Serving Spike

| | |
|---|---|
| **Date** | 2026-08-23 |
| **Status** | active |
| **Index** | [plans/INDEX.md](INDEX.md) |
| **Amends** | [2026-08-23-initial-plan.md](2026-08-23-initial-plan.md) (Phase 0 detail) |

## Question

Upstream documents serving MiniMax Music 3 on **two CUDA GPUs**. This project
(decision D1) targets **one RTX 4090 (24 564 MiB)**. Can `sgl-omni` serve the full
pipeline — Qwen3-8B global LLM + RVQ AR stage AND Flow Matching 2.4B + Flow-VAE
decode stage — on this single card?

## Pre-registered criteria (written before the experiment)

| Outcome | Criterion | Consequence |
|---|---|---|
| **GO** | Server reaches healthy state AND completes one end-to-end generation of ≥30 s audio without OOM | Proceed to full pipeline execution on single GPU |
| **GO-WITH-LIMITS** | Healthy server, but only with reduced scope (shorter max_new_tokens, quantization, offload) — record exact working configuration | Proceed within recorded limits; document constraints in configs |
| **NO-GO** | CUDA OOM during startup or first generation even after documented levers (both stages pinned to GPU 0, memory-fraction tuning) are exhausted | Stop; record measurements; discuss alternatives with owner |

Levers allowed before declaring NO-GO (in order):
1. Pin both pipeline stages to GPU 0 (`CUDA_VISIBLE_DEVICES=0`).
2. Reduce `--mem-*` / memory-fraction style flags if sgl-omni exposes them.
3. Shorten `max_new_tokens` for the smoke test (target ≥30 s audio ≈ ~1500 frames).

Not allowed: multi-GPU configs (defeats D1), model surgery/quantization beyond
flags upstream ships.

## Environment at time of spike

- WSL2 Ubuntu-24.04 (fresh distro installed today), GPU passthrough verified
  (`nvidia-smi` inside WSL: RTX 4090, 24 564 MiB, driver 591.86).
- venv `/root/agentic-music-venv`: torch 2.11.0+cu130, CUDA available: true,
  sglang-omni installed from PyPI (see env_setup/v1 `"ok": true`).
- Weights: `hf download MiniMaxAI/MiniMax-Music3` → `/root/models/minimax-music3`.

## Measurements

| Metric | Value |
|---|---|
| Steady-state VRAM after healthy startup | **23 954 MiB** / 24 564 MiB (97.5%) |
| AR stage weight load | 16.01 GB; KV cache allocated: 21 907 tokens (K+V ≈ 3.0 GB) |
| DiT/DAV stage | loaded bf16 on cuda:0, READY |
| Smoke generation | **OK**: 11.2 s audio (32 kHz stereo), seed 7, 750 frames, 53.7 s wall incl. first-use JIT compile |
| Smoke audio quality | peak −10.4 dBFS, mean −29.9 dBFS, LUFS −25.9, trailing silence 0.0 s |

## Result

**GO-WITH-LIMITS** — single RTX 4090 serves and generates successfully with this
exact configuration (all recorded in [configs/music3-pipeline.yaml](../configs/music3-pipeline.yaml)
+ [configs/provider.toml](../configs/provider.toml)):

1. Default topology already places both GPU stages (`minimax_music3_ar`,
   `dit_dav`) on `gpu: 0` in two processes — no `--colocate` needed
   (**`--colocate` is Qwen3-Omni-only** and errors out for Music 3).
2. `dit_dav.dtype`: float32 → **bfloat16** (float32 does not fit next to the
   8B AR weights).
3. AR `sglang_server_args.mem_fraction_static`: default 0.5 → **0.85**
   (0.5 left no room for the KV cache).
4. AR `server_args_overrides.cuda_graph_backend_decode: disabled` — flashinfer
   JIT capture needs nvcc; graphs off trade decode speed for bootability.
5. WSL needs a minimal CUDA toolchain for flashinfer's lazy JIT:
   `cuda-nvcc-13-1` + `cuda-cudart-dev-13-1` from NVIDIA's apt repo (plus
   `ninja-build`, `build-essential`, `python3-dev`) — all provisioned by
   `scripts/env_setup.sh`.

## Operational findings (recorded for AGENTS.md / env-setup skill)

- The Ubuntu-24.04 WSL image runs systemd: **session-scoped daemons are
  SIGKILLed when the launching console disconnects** (silently — buffered logs
  are lost). Servers must run in the foreground of a persistent background job
  (`scripts/serve.py run`); self-daemonizing via setsid/nohup dies.
- `wsl.exe` strips embedded quotes when passing argv; inner commands must avoid
  nested quoting (use script files under `scripts/`).
- VRAM headroom at steady state is ~600 MiB; longer generations may still OOM.
  If that happens, next levers: lower `mem_fraction_static` (smaller KV pool),
  or `server_args_overrides.quantization: fp8` for the AR stage.

## Full-song validation

Three seeded takes of session `20260823-105740-first-light` generated at full
length (max_new_tokens 9000) immediately after the GO verdict:

| Take | Seed | Wall time | Duration | Peak dBFS | LUFS | CLAP | Flags |
|---|---|---|---|---|---|---|---|
| take-01 | 7 | 688.5 s | 209.0 s (3:29) | −2.3 | −22.4 | **0.5343** | — |
| take-02 | 42 | 608.0 s | 178.0 s (2:58) | −1.5 | −18.6 | 0.5226 | — |
| take-03 | 1234 | 728.3 s | 227.4 s (3:47) | −0.0 | −18.3 | 0.5305 | peak-at-zero |

VRAM during full generation: sampled every 2 s, 874 samples,
**max 24 113 MiB** (~450 MiB headroom), no OOM events across ~34 min of
continuous inference. Recommended take: `take-01` (see session `review.json`).
