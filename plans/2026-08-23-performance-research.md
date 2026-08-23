# Performance Research — Generation Speed & Memory

| | |
|---|---|
| **Date** | 2026-08-23 |
| **Status** | active |
| **Index** | [plans/INDEX.md](INDEX.md) |
| **Amends** | [2026-08-23-phase0-single-gpu-spike.md](2026-08-23-phase0-single-gpu-spike.md) |

Sources: official SGLang-Omni cookbook
(sgl-project.github.io/sglang-omni/cookbook/minimax_music3.html),
`sglang_omni` 0.1.3 source inspection, controlled benchmarks below.

## Model timing model (from upstream docs)

- Backbone decodes ONE frame per step (8 RVQ codebooks via 4-layer depth
  decoder); 25 frames/second; cap 9 000 frames ≈ 6 min.
- Every 200 frames (100-frame hop) hand a chunk to the flow-matching DIT:
  Euler solver, fixed **30 steps**, CFG scale 1.7 — then DAC decode.
- Classifier-free guidance is hard-fixed in both stages, no flag exists; every
  request occupies TWO decode rows (doubles KV, nearly free in time because the
  AR stage is weight-bandwidth-bound).
- Upstream defaults that are ON with no flags: backbone decode CUDA graph,
  RVQ depth CUDA graph, compiled DIT blocks, compiled DAV decoder,
  batched seeded sampling.

## Experiments & results (single RTX 4090)

| Experiment | Result | Decision |
|---|---|---|
| Re-enable backbone decode CUDA graphs (nvcc now provisioned by env_setup.sh) | Smoke A/B (seed 7, 750 frames): **32.7 s → 28.6 s (−12.5%)**, byte-identical output — graphs don't perturb numerics | ✅ **ADOPTED** (override removed from configs/music3-pipeline.yaml; capture verified bs=1…32) |
| 3 takes concurrently (identical prompts) | Total wall 115 s vs ≈87 s sequential — **slower**. Two stages contend on one die: DIT chunks serialize on their process; AR rows add bandwidth pressure without adding compute | ❌ REJECTED for single-GPU; revisit only for multi-GPU hosts |
| `cache_dit` | Upstream: "approximate … trades audio quality for speed" | 🚫 Rejected — quality regression unacceptable (see 2026-08-23-quality-regression-fix.md) |
| `dit_steps` < 30 | Upstream: "measurably a quality reduction rather than a free win" | 🚫 Rejected |
| DiT attention backend swap (`fa`/`sage_attn`) | Requires bfloat16 — conflicts with float32 synthesis decision; `torch_sdpa` is upstream's measured fastest anyway | 🚫 Rejected |
| Lower `mem_fraction_static` | Upstream measured ~6% slower at 0.35 | 🚫 Rejected (we run 0.85) |

## Net effect of adopted changes

- Decode CUDA graphs: ~12% wall-time reduction on top of the float32+fp8
  quality config; zero quality impact (byte-deterministic per seed).
- Memory: steady state unchanged at ~23.6 GiB (fp8 AR backbone from the
  quality fix remains the memory win); KV pool 66 992 tokens.

## Workflow guidance derived from upstream notes

1. Iterate captions on **short clips first** (`max_new_tokens` 300–750);
   render full length once the style is right — cost scales with frames.
2. Lyrics section tags MUST sit on their own line; text sharing a tag's line
   is silently dropped by normalization.
3. Byte-identical lyrics + caption reproduce exactly (same seed); whitespace
   rewrites change audio. Never "tidy" files between regeneration rounds.
4. Sampling params (temperature/top_p/etc.) are rejected by the API, not
   ignored — do not add them to generate.py.

## Open ideas (not scheduled)

- fp8 KV cache dtype (memory-only win; would matter for >3 concurrent takes on
  bigger cards)
- `breakable_cuda_graph` for the acoustic stage (upstream threshold logic
  suggests it targets large-VRAM headroom situations)
