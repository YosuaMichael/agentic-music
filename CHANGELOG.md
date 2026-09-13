# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **YuE2 as a second music model, and the new default** (plan:
  [plans/2026-09-13-yue2-default-model.md](plans/2026-09-13-yue2-default-model.md)).
  YuE2-3B scores highest among open models on WildSongBench (SongBench Avg 6.73 vs
  MiniMax Music 3's 6.28 and Suno v5's 6.87), renders a ~3.6-minute song in ~71 s at
  ~11 GB peak on a 4090, and emits an **editable melody + chord score** per take.
  It is Linux-only upstream, so on Windows it runs in the same WSL2 distro the
  SGLang reference path uses.
  - `scripts/select_model.py` (`select_model/v1`) — the **ask-once** model choice:
    resolves the registry, probes per-model availability/readiness, and reads/writes
    `<session>/model.json`. `needs_choice` is the gate the skills ask on; once
    recorded the question is never repeated, and an existing choice is never
    silently overwritten.
  - `scripts/setup_yue2.py` (`setup_yue2/v1`) — idempotent machine bring-up: venv
    inside the runtime, install from the pinned upstream checkout (v0.1.6 wheel as an
    explicit fallback), ~7.8 GB of weights, then a `yue2 doctor` + CUDA gate.
  - `scripts/generate_yue2.py` (`generate/v1`) — one seeded take: writes the exact
    upstream request JSON, runs `yue2 generate` in the runtime, and produces the
    standard session artifacts plus `take-NN.flac`, `take-NN.request.json`, the frozen
    `take-NN.style.txt` prompt, and the upstream native artifacts under
    `take-NN.yue2/` (`score.abc`, `plan.json`, `result.json`, `latent.npy`).
  - `scripts/generate_take.py` (`generate/v1`) — model→generator dispatch in one
    place, used by the generate-song skill. Reports `model` and `model_source`
    (`session` | `default` | `flag`) on every result.
  - New session artifact **`style.txt`**: YuE2's short comma-separated style prompt,
    distinct from Music 3's ~400-word Structured Caption. compose-brief now writes
    both from the same interview; each model reads its own native prompt.
  - New model registry in `configs/provider.toml` (`[models]` + `[yue2]`), keeping
    the *model* axis separate from the *engine* axis.
- **`model-guide` skill** — a per-model parameter and capability reference. The models
  are deliberately **not** standardised: each section documents that model's own request
  fields, CLI flags, defaults, capabilities, limits, and measured performance, so an
  agent can drive whichever model natively. It also carries the ask-once decision table
  (license, instrumentals, prompt artifact, length control).
- **`--extra-arg` model-native passthrough** on the dispatcher and on every generator
  (`--extra-arg "--quantization fp8"`, repeatable, shell-split). Model-specific flags
  reach the model's own CLI without a code change, so flexibility does not depend on
  normalising the models. Flags that carry the session file contract or would falsify a
  take's provenance are rejected with the first-class alternative named; whatever is
  passed is recorded in `take-NN.metadata.json` (`extra_args` / `extra_payload`).
- **YuE2 verified end to end, with measured performance.** `setup_yue2.py` installed
  v0.1.6 and ~7.8 GB of weights in WSL2; three real takes rendered in
  `studio/sessions/20260913-233400-yue2-first-song/`: **107.8 s song in 45.5 s of model
  time (RTF 0.42), 54.7 s end to end, ~9.3 GiB peak** on an RTX 4090. `cot=off` renders
  in 35.8 s. The same seed reproduces byte-identical WAV/FLAC/MP3.
- Per-take `generate.log` retained in `takes/take-NN.yue2/`: the model's own stage
  timings and token throughput, for benchmarking and debugging.

### Fixed

- **Corrected: instrumental-only is unsupported by BOTH models, not just YuE2.**
  MiniMax Music 3 was documented (and configured) as the instrumental path via an
  empty `lyrics.txt`; the owner reports it always sang regardless, and three
  2026-08-27 studio learnings entries record successively stronger caption/lyrics
  strategies failing the same way. `[models.minimax-music3].supports_instrumental`
  is now `false`, so **no shipped model renders instrumentals**; compose-brief says
  so before any GPU time; an empty `lyrics.txt` on MiniMax now returns a
  machine-readable `warnings` entry instead of quietly delivering vocals; and the
  YuE2 refusal no longer points users at MiniMax as an alternative. Locked in by
  tests that fail if any registry entry re-claims instrumental support —
  [plans/2026-09-14-instrumental-generation-unsupported.md](plans/2026-09-14-instrumental-generation-unsupported.md).
- **YuE2 generation is now offline by default** (`[yue2].offline = true`). Online, an
  identical take spent ~250 s revalidating already-present weights over ~46 Hugging Face
  connections (299.5 s total vs 54.7 s offline). `setup_yue2.py` remains the step that
  fetches weights.
- `RunResult.ok` was missing on the YuE2 generator's runtime helper (added to all three
  runtime helpers, with tests that exercise it against a real subprocess exit code).

### Changed

- **The default music model is now `yue2`** (`[models].default`). MiniMax Music 3
  remains fully supported by selecting `minimax-music3` — its owner-approved
  audio.cpp Q8 default is unchanged.
- generate-song dispatches through `scripts/generate_take.py` instead of picking a
  backend script, and reads the session's model instead of `[provider].type`.
- compose-brief begins by asking which model to use **once per song**, with the
  license (YuE2 weights are CC BY-NC 4.0, non-commercial) and the instrumental
  limitation stated in the question.
- judge-quality scores each take against the prompt that actually produced it —
  `take-NN.style.txt` for YuE2 takes, `take-NN.caption.md` for Music 3 takes — and
  records `model` + `prompt_scored` in `review.json`.
- studio/AGENTS.md and the env-setup, compose-brief, generate-song and judge-quality
  skills updated for two models.
- `scripts/fetch_upstream.sh` pins the YuE2 repository as a third upstream
  (`oss/yue2`), which is also the install source for the YuE2 runtime.
- Artifact player pages now lead with the prompt the take was **actually rendered
  from** — `style.txt` for YuE2 takes, `caption.md` for Music 3 takes — and label the
  other one as unused, instead of always showing the caption. The JSON inventory
  (`artifacts-index/v1`) additionally reports each take's `model` and the session's
  `has_style`/`has_model_choice`.

### Fixed

- Pipeline test loader now registers modules in `sys.modules`, so scripts defining
  dataclasses (YuE2 runtime plumbing) import cleanly under test.

### Security

- YuE2 weight licensing is surfaced wherever a choice is made or documented
  (registry metadata, ask-once prompt, README, NOTICE): **CC BY-NC 4.0,
  non-commercial only**. No upstream content is vendored; our wrappers are original.

### Added (studio learnings & provenance)

- Provenance for YuE2 takes includes the machine-readable request and the symbolic
  score, and a failed attempt's native directory is retired as `*_failed` rather than
  deleted, so retries keep their evidence.
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

### Changed (workspace split)

- Repository split into two agent workspaces: `studio/` (lean creator manual,
  songs under `studio/sessions/`) and repo root (development). Skills moved
  to `.dsh/skills/` — DSH's native discovery root, so every skill is
  auto-cataloged in each project session.
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
