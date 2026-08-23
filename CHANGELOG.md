# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Audio-quality regression in the single-GPU recipe: forcing the acoustic stage
  (flow-matching DiT + VAE decoder) to bfloat16 produced noisy, breaking output.
  `configs/music3-pipeline.yaml` now keeps synthesis in float32 (TF32) and
  quantizes the AR backbone to fp8 instead — see
  [plans/2026-08-23-quality-regression-fix.md](plans/2026-08-23-quality-regression-fix.md)
  for the A/B evidence.

### Added

- `plans/` folder with the initial plan document, the open-source standards addendum, and
  the Phase 0 single-GPU spike record.
- Project scaffold: AGENTS.md operating manual; `env-setup`, `compose-brief`,
  `generate-song`, and `judge-quality` skills; deterministic JSON-out scripts
  (`hardware_audit.py`, `env_setup.sh`, `fetch_upstream.sh`, `serve.py`, `generate.py`,
  `analyze_audio.py`, `clap_score.py`, `vram_sampler.sh`); provider configuration;
  pytest + ruff quality gates.
- Open-source community files (LICENSE, README, CONTRIBUTING, CODE_OF_CONDUCT,
  SECURITY, NOTICE, .gitignore, GitHub issue/PR templates) per the standards addendum.
- Single-GPU serving recipe for MiniMax Music 3 on one 24 GB CUDA GPU
  (`configs/music3-pipeline.yaml`): bfloat16 DiT stage, AR memory fraction 0.85,
  decode CUDA graphs disabled — see the Phase 0 plan document for measurements.

### Validated

- End-to-end local pipeline on a single RTX 4090 under WSL2 Ubuntu-24.04:
  weights download → SGLang-Omni serve → three full seeded takes of a first song
  (`sessions/20260823-105740-first-light/`) → audio metrics + CLAP alignment scoring
  with ranked verdict in that session's `review.json`.
- Final configuration (float32 synthesis + fp8 AR backbone) **confirmed by owner
  listening** — regenerated takes judged clean; bf16 set superseded.
