# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Per-take provenance snapshots**: every generation now freezes the exact
  `caption.md` / `lyrics.txt` / `caption.json` that produced it into
  `takes/take-NN.caption.md`, `.lyrics.txt`, `.caption.json` — lyric and
  caption revisions at the session root no longer orphan or misattribute
  older renders. judge-quality scores each take against its own snapshot
  when present.
- **Studio learnings system** (`studio/learnings/`, gitignored per-machine):
  append-only mistake memory consulted at the start of every creation skill;
  corrective feedback from the user becomes a dated Symptom/Cause/Rule entry
  in the same turn, so repeated mistakes are prevented dynamically. Seeded
  with four real lessons (lost background jobs, trust-disk-not-tool-results,
  lyric-tag line loss, byte-exact reproducibility).
- **Interactive generation flow**: generate-song now asks how many takes to
  render (config default only as suggestion), reports per-take quick facts
  (duration, wall time, RTF, MP3 size, player links) after rendering, and
  runs auto-judgement only when the user explicitly opts in.

### Changed

- Repository split into two agent workspaces: `studio/` (lean creator manual,
  songs under `studio/sessions/`) and repo root (development). Skills moved
  to `.dsh/skills/` — DSH's native discovery root, so all four skills are
  auto-cataloged in every project session.
- Artifact server (`serve_artifacts.py`) defaults to serving
  `studio/sessions/`.

### Added (post-0.0.1 batch)

- Artifact sidecar for harness web integration (`scripts/serve_artifacts.py`,
  `artifacts-index/v1`): read-only HTTP server over `sessions/` with HTML
  player index, per-take player pages (`/play/...`: playback, metadata,
  download button, sibling takes), JSON inventory, HTTP Range streaming,
  path-traversal guard, and optional token auth — designed to sit behind
  Tailscale Serve for multi-device browser access.
- MP3 companions: `scripts/transcode.py` (`transcode/v1`, ffmpeg libmp3lame
  VBR) invoked automatically by the audiocpp generator when
  `[audiocpp].mp3 = true` — ~7× smaller downloads, WAV masters preserved.

## [0.0.1] - 2026-08-23

First working release: a fully local, agent-executable music studio built
around open-weights MiniMax Music 3 on a single consumer CUDA GPU.

### Added

- Project scaffold: AGENTS.md operating manual; `env-setup`, `compose-brief`,
  `generate-song`, and `judge-quality` skills; deterministic JSON-out scripts
  (`hardware_audit.py`, `env_setup.sh`, `fetch_upstream.sh`, `serve.py`,
  `generate.py`, `analyze_audio.py`, `clap_score.py`, `vram_sampler.sh`);
  provider configuration; pytest + ruff quality gates.
- Open-source community files (LICENSE, README, CONTRIBUTING, CODE_OF_CONDUCT,
  SECURITY, NOTICE, .gitignore, GitHub issue/PR templates) per the standards
  addendum.
- Single-GPU serving recipe for MiniMax Music 3 on one 24 GB CUDA GPU
  (`configs/music3-pipeline.yaml`) — see the Phase 0 plan document for
  measurements.
- **audio.cpp GGUF provider (now the default)**: pure-C++ ggml runtime running
  all-Q8 quantized components Windows-natively — no WSL or Python server
  required for generation. Full-length songs render ~4× faster than the
  SGLang-Omni reference stack with 29% lower peak VRAM
  ([plans/2026-08-23-audiocpp-gguf-provider.md](plans/2026-08-23-audiocpp-gguf-provider.md)).
  Provider selection lives in `configs/provider.toml` (`type = "audiocpp" |
  "local"`); machine bring-up via idempotent `scripts/setup_audiocpp.py`.
- `scripts/generate_audiocpp.py` emitting the same `generate/v1` session
  contract as `scripts/generate.py` (plus additive `provider`/`rtf` fields).
- Performance research record with measured A/Bs
  ([plans/2026-08-23-performance-research.md](plans/2026-08-23-performance-research.md)):
  backbone decode CUDA graphs adopted (+12.5% on the SGLang path,
  byte-identical output per seed); concurrent take dispatch tested and
  rejected for single-GPU hosts; quality-sensitive knobs (`cache_dit`,
  reduced `dit_steps`) documented as rejected.
- compose-brief skill: offline manual-fallback procedure for caption expansion
  via the vendored upstream skill checkout, plus a machine-readable
  `caption.json` session artifact contract.
- `agents/openai.yaml` interface metadata for all four skills.

### Fixed

- Audio-quality regression in the single-GPU recipe: forcing the acoustic stage
  (flow-matching DiT + VAE decoder) to bfloat16 produced noisy, breaking
  output. Synthesis now stays float32 (TF32) while the AR backbone runs fp8 —
  see
  [plans/2026-08-23-quality-regression-fix.md](plans/2026-08-23-quality-regression-fix.md)
  for the A/B evidence.

### Validated

- End-to-end local pipeline on a single RTX 4090:
  weights download → serve → three full seeded takes of a first song
  (`sessions/20260823-105740-first-light/`) → audio metrics + CLAP alignment
  scoring with ranked verdict in that session's `review.json`. Final SGLang
  configuration confirmed by owner listening.
- audio.cpp Q8 provider confirmed by owner listening against the SGLang
  reference on identical prompts (A/B session); the lighter q4 component mix
  was also owner-listened ("also good") but kept off-default since it offers
  no speed benefit over Q8.

[0.0.1]: https://github.com/YosuaMichael/agentic-music/releases/tag/v0.0.1
