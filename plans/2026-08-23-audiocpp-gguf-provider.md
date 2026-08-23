# audio.cpp GGUF Provider Evaluation

| | |
|---|---|
| **Date** | 2026-08-23 |
| **Status** | active |
| **Index** | [plans/INDEX.md](INDEX.md) |
| **Amends** | [2026-08-23-performance-research.md](2026-08-23-performance-research.md) |

## Motivation

Owner proposal: try the community-quantized
[audio-cpp/MiniMax-Music3-GGUF](https://huggingface.co/audio-cpp/MiniMax-Music3-GGUF)
(25k+ downloads) served by [audio.cpp](https://github.com/0xShug0/audio.cpp)
release 0.6.1 — a pure-C++ ggml runtime claiming Q8 packages up to **1.53×
faster with ~37% less peak VRAM**, and CUDA paths up to 8× over Python
reference implementations.

## What was installed

- `audiocpp-windows-cuda-balance` release binaries + CUDA runtime pack →
  `.tools/audiocpp/` (gitignored): `audiocpp_cli.exe`, `audiocpp_server.exe`,
  cublas/cufft CUDA-13 DLLs. CLI verified: RTX 4090 visible (cc 8.9).
- Q8 component set downloaded from HF into
  `models/audiocpp/MiniMax-Music3-GGUF/` (gitignored):
  `language_model_q8_0.gguf` 9.21 GB · `transformer_q8_0.gguf` 2.43 GB ·
  `rvq_depth_decoder_q8_0.gguf` 0.66 GB · `vocoder.gguf` 0.20 GB ·
  `condition_encoder.gguf` 0.09 GB + configs/tokenizer.
  Total ≈ **12.6 GB** vs ~23.6 GiB steady state for the SGLang stack.

## Faithfulness of the port

The CLI exposes the exact Music 3 sampling contract as session/request options:
`num_inference_steps=30`, `guidance_scale=1.7`, `ar_guidance_scale=1.5`,
`top_k=50`, `seed`, `duration_sec` (= AR frame budget ÷ 25 fps, equivalent to
`max_new_tokens`). Defaults match upstream Python behavior.

## Integration

- New provider section `[audiocpp]` in [configs/provider.toml](../configs/provider.toml);
  switch by setting `[provider] type = "audiocpp"` (SGLang config preserved).
- New script [scripts/generate_audiocpp.py](../scripts/generate_audiocpp.py)
  emitting the same `generate/v1` contract (+ additive `provider`/`rtf` fields)
  so sessions, judging, and skills work unchanged. No server process needed —
  the CLI loads weights per invocation.

## Benchmarks — measured 2026-08-23

Same machine, same prompts, seed 7. SGLang numbers from
[2026-08-23-performance-research.md](2026-08-23-performance-research.md) and
the phase-0 spike.

| Metric | SGLang float32+fp8+graphs | audio.cpp Q8 | Δ |
|---|---|---|---|
| 30 s clip wall time | 28.6 s (warm server) | ~17–39 s cold CLI incl. load | ≈parity warm |
| **Full song (~200 s) wall** | ~16–19 min | **4 min 03 s** | **~4–4.7× faster** |
| Peak VRAM (full length) | 23 621 MiB steady / 24 113 peak | **16 808 MiB** | **−29%** |
| Peak VRAM (30 s clip) | — | 14 190 MiB | −40% vs steady |
| LUFS envelope | −13.0…−14.3 | −13.87 (clip) / −14.38 (song) | ✅ healthy |
| Determinism per seed | byte-identical | byte-identical (MD5 verified) | ✅ |
| Output format | 32 kHz stereo WAV | 44.1 kHz stereo WAV | note: analyze/judge handle both |
| Owner listening | ✅ confirmed clean | ⬜ pending — A/B session `sessions/00000000-000000-audiocpp-ab/` | gate |

## Integration notes discovered

1. Release 0.6.1 validates the DEFAULT package file list (`language_model_q4_0.gguf`,
   `transformer_q4_0.gguf`) before honoring component `--session-option`
   overrides; with all files present the overrides still did not take effect
   on this build. Workaround: sibling dir `models/audiocpp/Music3-GGUF-q8asdefault/`
   NTFS-hardlinks the Q8 GGUFs under default names (zero extra disk).
   Re-test overrides when upgrading audio.cpp.
2. CUDA runtime DLLs ship separately (`audiocpp-windows-cuda-runtime.zip`);
   without them the CLI exits silently.
3. `duration_sec` is a budget, not a hard cap — model self-ends on the audio-end
   token exactly like `max_new_tokens` upstream.
4. `mem_saver=true` (default) loads large stages only while needed — key to the
   low peak VRAM.

## Decision

**ADOPTED as default provider, 2026-08-23.** Owner listened to both A/B takes
and confirmed: *"it sounds good and clear."* All three criteria met:

1. Quality: ✅ owner-approved (the binding gate)
2. Speed: ✅ ~4–4.7× faster at full length
3. VRAM: ✅ −29% peak full-length / −40% short clips

Changes made on adoption:

- `configs/provider.toml` `[provider].type = "audiocpp"` (SGLang config
  preserved under `[local]`; flip back by setting `"local"`).
- `scripts/setup_audiocpp.py` — idempotent machine bring-up for this provider
  (`setup_audiocpp/v1`): pinned binary/runtime downloads, GGUF component set,
  hardlink-dir assembly.
- `skills/generate-song/SKILL.md` — dual-provider procedure.
- `skills/env-setup/SKILL.md` — path A (audiocpp, default) vs path B (SGLang);
  new Step 4a.

The SGLang float32+fp8 stack remains the fidelity reference and fallback;
take-for-take comparisons across providers are not meaningful (different
sampling implementations), so sessions record their provider in take metadata.
