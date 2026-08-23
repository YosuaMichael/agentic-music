# Audio Quality Regression & Fix — bfloat16 Synthesis vs float32 + fp8 AR

| | |
|---|---|
| **Date** | 2026-08-23 |
| **Status** | active |
| **Index** | [plans/INDEX.md](INDEX.md) |
| **Amends** | [2026-08-23-phase0-single-gpu-spike.md](2026-08-23-phase0-single-gpu-spike.md) |

## Problem

All three full takes of session `20260823-105740-first-light`, generated under the
Phase 0 GO configuration (**bfloat16** DiT/DAV), sounded broken to the owner:
"breaking sounds and a lot of noise" — far below the official upstream sample
(`oss/minimax-music3/assets/minimax_ttm.wav`).

## Root cause

To fit one 24 GB card, Phase 0 forced the entire acoustic stage — flow-matching
DiT **and** VAE waveform decoder (`dav.pth`) — to bfloat16
(`acoustic.py` applies one `dtype` to both). The upstream reference is rendered
with `dtype=float32`, which upstream makes affordable via TF32 ("0.22% from the
true float32 DIT solve while running 4.4x faster" — their own source note).
Waveform synthesis in bf16 produced exactly the reported artifacts.

Objective corroboration: bf16 take loudness profile was anomalous
(−25.9 LUFS mean of batch) versus the upstream reference (−14.5 LUFS).

## Fix: hybrid precision

Quality-critical synthesis restored to float32; the perceptually robust token
side quantized instead:

| Stage | Before (broken) | After (fix) |
|---|---|---|
| dit_dav (DiT + VAE decoder) | bfloat16 (~5 GB) | **float32 + TF32 (~10 GB)** |
| minimax_music3_ar (Qwen3-8B backbone) | bf16 (~16 GB) | **fp8 (~9.8 GB)** via `server_args_overrides.quantization: fp8` |
| KV cache | 21 907 tokens | 66 992 tokens |
| Steady-state VRAM | 23 954 MiB | **23 658 MiB** (more headroom!) |

Config lives in [configs/music3-pipeline.yaml](../configs/music3-pipeline.yaml);
fp8 runs on Ada (sm_89) hardware; decode CUDA graphs remain disabled (flashinfer
JIT needs nvcc — graphs are speed-only, not quality).

## A/B evidence (same seed 7, same 750-frame smoke prompt)

| Metric | bf16 take-01 | float32+fp8 take-02 | upstream reference |
|---|---|---|---|
| Wall time | 53.7 s | **32.7 s** | — |
| Integrated LUFS | −25.93 | **−12.45** | −14.46 |
| Peak dBFS | −10.4 | −0.0 | −0.0 |
| Mean volume dBFS | −29.9 | −16.4 | −16.6 |

The fixed take's loudness/peak profile now sits on top of the upstream
reference envelope; final confirmation is the owner listening to the
regenerated full takes.

## Full regeneration results

Three full takes regenerated under the fix (session
`20260823-105740-first-light`, takes 04–06; bf16 set kept as superseded):

| Take | Seed | Wall time | Duration | Peak dBFS | LUFS | CLAP |
|---|---|---|---|---|---|---|
| take-04 | 7 | ~965 s | 201.1 s | −0.0 | −12.99 | 0.5377 |
| take-05 | 42 | ~1057 s | 215.8 s | −0.0 | −14.33 | **0.6012** |
| take-06 | 1234 | ~1141 s | 208.6 s | −0.0 | −13.11 | 0.548 |

Batch LUFS envelope matches the upstream reference (−14.46); best CLAP score of
the session. **Confirmed by owner listening (2026-08-23): "clean and nice" —
quality regression resolved.**

## Consequences

1. `configs/music3-pipeline.yaml` header updated; never set `dit_dav.dtype`
   to anything but float32 without re-running this A/B.
2. Full regeneration of session `20260823-105740-first-light` launched
   (new takes supersede the bf16 set per session protocol — originals kept).
3. README/CHANGELOG notes updated after owner confirms quality by ear.
