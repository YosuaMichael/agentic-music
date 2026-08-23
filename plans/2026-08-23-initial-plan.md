# Agentic Music — Initial Plan

| | |
|---|---|
| **Date** | 2026-08-23 |
| **Status** | active |
| **Index** | [plans/INDEX.md](INDEX.md) |

## 1. Objective

Build a repository where any coding agent (DeepSeek Harness, Claude Code, Codex, …) can
execute an end-to-end local music generation pipeline by following written instructions:

1. **Setup environment** — audit hardware, create isolated Python env, download suitable
   model weights, launch and health-check the inference server.
2. **Compose music and style** — interview the user, negotiate a creative brief, produce a
   Structured Caption for MiniMax Music 3.
3. **Generate music** — call the locally served MiniMax Music 3 model to produce songs.
4. **Judge quality (optional stage)** — score generated takes objectively and rank them.

The user chose **pure local generation on the single RTX 4090** (no hosted-API fallback).

## 2. Decisions Locked (2026-08-23)

| # | Decision | Choice |
|---|----------|--------|
| D1 | Inference target | Single RTX 4090 (24 GB) only; hosted MiniMax API explicitly out of scope for now |
| D2 | Agent runtime target | Agent-neutral `AGENTS.md` + `skills/` convention (not Claude- or DSH-specific) |
| D3 | Python tooling | `uv` (already installed, v0.10.0) for env + dependency management |
| D4 | Quality judging depth | Audio metrics (duration/LUFS/clipping/silence) + CLAP text–audio alignment; no LLM-as-judge for now |

## 3. Environment Facts (as of 2026-08-23)

| Item | Value |
|------|-------|
| OS | Windows, WSL2 present (default distro `docker-desktop` — not usable for dev; a real Ubuntu distro must be installed) |
| GPU | 1× NVIDIA GeForce RTX 4090, 24 564 MiB, driver 591.86 |
| Python | 3.12.12 (Windows side) |
| uv | 0.10.0 |
| Working dir | `C:\Users\Mike\repo\poc\agentic_music` |

## 4. Upstream Assets Inventory (vendored, read-only under `oss/`)

### 4.1 `oss/minimax-music3/` — official MiniMax Music 3 repository

- Open weights: `hf download MiniMaxAI/MiniMax-Music3` (Hugging Face, community license —
  acceptable for personal/local use; re-check before any commercial use).
- Architecture: 8B global LLM (Qwen3-8B init) + 0.6B local LLM + Flow Matching (2.4B) +
  Flow-VAE decoder (123M); outputs 32 kHz stereo WAV; songs up to ~5 minutes.
- Serving: **SGLang-Omni** (`sgl-omni serve --model-path MiniMaxAI/MiniMax-Music3`).
  README documents **two CUDA GPUs** (GPU 0: AR/RVQ stage; GPU 1: flow-matching/decode
  stage) — this is the project's central technical risk on our single-GPU machine (§8).
- API shape: shared speech API — `POST /v1/audio/speech` with lyrics in `input`, music
  description in `instructions`; non-streaming only; ≤5 000 prompt tokens; ≤9 000 frames.
- Ships official agent skill [`music-caption-rewriter`](../oss/minimax-music3/skills/music-caption-rewriter/SKILL.md):
  expands a brief description + tagged lyrics into a Music 3.0 Structured Caption
  (Global Metadata / Vocal Details / Arrangement) using 18 style-family indexes and
  ~1 000 caption templates. Pure text library, no runtime deps.

### 4.2 `oss/skills/` — MiniMax agent-skills collection

- [`minimax-music-gen`](../oss/skills/skills/minimax-music-gen/SKILL.md) (MIT): drives the
  **hosted** MiniMax API via the `mmx` CLI (models `music-2.6-free`, `music-cover-free`).
  We do **not** use its execution layer (cloud API conflicts with D1), but we **adopt its
  interaction design** into our compose-brief skill:
  - intent detection decision tree (vocal / instrumental / cover × Basic / Advanced mode),
  - iterative lyric editing ("change the second chorus" → targeted rewrite),
  - preview-and-confirm before spending generation compute,
  - post-generation feedback loop (love / adjust / fine-tune / restart) with versioned files,
  - error-handling table agents can follow mechanically,
  - language rules (conversation in user language, generation prompts in English),
  - timestamped-slug output naming.
  Its [`references/prompt_guide.md`](../oss/skills/skills/minimax-music-gen/references/prompt_guide.md)
  (vivid-sentence prompting, genre/vocal/instrument/BPM vocabulary tables) is required
  reading for the composing agent during interviews.
- `minimax-music-playlist`: cloud-only taste-profiling/multi-song skill — out of scope.
- Cover mode (`music-cover-free`) has **no local equivalent** in Music 3; noted as a future
  capability that would arrive only with a hosted provider config.

## 5. Repository Design

```
agentic_music/
├── AGENTS.md                    # THE entrypoint for any agent: workflow, rules, session protocol
├── README.md                    # human-facing overview
├── plans/                       # this folder: dated, indexed plan documents
├── skills/
│   ├── env-setup/SKILL.md       # hardware audit → uv venv → weights → serve → healthcheck
│   ├── compose-brief/SKILL.md   # interview protocol → brief.md → $music-caption-rewriter → caption.md
│   ├── generate-song/SKILL.md   # caption + lyrics → N seeded takes via scripts/generate.py
│   └── judge-quality/SKILL.md   # audio metrics + CLAP alignment → review.json verdict
├── scripts/                     # deterministic JSON-out CLIs — agents call these, never improvise
│   ├── hardware_audit.py        #   GPU / VRAM / driver / disk report
│   ├── env_setup.sh             #   WSL2-aware uv environment, torch+CUDA verification
│   ├── download_model.py        #   resumable hf download + integrity check
│   ├── serve.py                 #   sgl-omni start / stop / status / healthcheck, VRAM logging
│   ├── generate.py              #   POST /v1/audio/speech → WAV + metadata.json
│   ├── analyze_audio.py         #   duration, LUFS, clipping, trailing silence
│   └── clap_score.py            #   caption↔audio semantic alignment score
├── sessions/<song-id>/          # all per-song state (see §7)
├── configs/provider.toml        # endpoint, seeds, generation defaults
└── oss/                         # vendored upstream checkouts, read-only reference (§4)
```

### Design principles

1. **State in files, not chat.** Every song is a `sessions/<song-id>/` folder with fixed
   artifact names; any agent resumes mid-pipeline by reading the folder.
2. **Agents orchestrate, scripts execute.** SKILL.md files instruct the agent to run
   deterministic scripts and parse their JSON output — no freehand curl/python during infra
   steps. This is what makes end-to-end execution reliable rather than lucky.
3. **Provider abstraction.** All generation goes through `generate.py` + `configs/provider.toml`,
   so the backend (local serve today; remote GPU or hosted API someday) is a config flip,
   not a rewrite.
4. **Vendored upstream stays read-only.** Our skills *reference* `oss/` material; nothing
   installs globally, nothing mutates upstream checkouts.

## 6. Composition Stack (how "style" gets made)

```
user idea
  → compose-brief skill: structured interview using minimax-music-gen protocol
    + prompt_guide vocabulary          → brief.md, lyrics.txt
  → official $music-caption-rewriter    → caption.md (Music 3.0 Structured Caption)
  → generate.py (caption as `instructions`, lyrics as `input`) → takes/*.wav
```

## 7. Session State Contract

Each song lives in `sessions/<song-id>/` (id = timestamped slug):

| Artifact | Produced by | Purpose |
|----------|-------------|---------|
| `brief.md` | compose-brief | Interview result: genre, mood, references, themes, constraints |
| `lyrics.txt` | compose-brief | Final lyrics with `[Verse]`/`[Chorus]`… section tags |
| `caption.md` (+ `.json`) | compose-brief | Structured Caption from `$music-caption-rewriter` |
| `takes/take-NN.wav` | generate-song | One seeded generation take |
| `takes/take-NN.metadata.json` | generate-song | Seed, params, timestamps, server info for reproducibility |
| `review.json` | judge-quality | Per-take metrics + CLAP scores + ranking |

## 8. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Single-GPU serving unproven (upstream documents 2×CUDA) | Blocks generation entirely (D1) | **Phase 0 feasibility spike before any building**: real Ubuntu WSL2 distro → CUDA-in-WSL check → weights download → single-GPU serve attempt → peak-VRAM measurement on short generation → recorded go/no-go. Levers if tight: pin both stages to GPU 0, memory-fraction tuning, phase offloading; community reports suggest far lower VRAM may work than README implies. |
| SGLang is Linux-first; Windows unsupported natively | Setup friction | Everything server-side runs inside WSL2 Ubuntu; scripts are WSL2-aware; Phase 0 validates early. Current default distro is `docker-desktop`, so a proper Ubuntu install is step one. |
| Long non-streaming generations (minutes per take) | Timeouts, stuck agents | `serve.py`/`generate.py` run as managed background jobs with health checks and explicit status polling. |
| Community license terms | Only matters commercially | Personal/local use fine; re-read license before any commercial release. |
| CLAP model adds ~2 GB | Disk/VRAM when judging | Judging runs while server idle; disk budget checked in `hardware_audit.py`. |

## 9. Roadmap

| Phase | Scope | Gate |
|-------|-------|------|
| **Phase 0** | Feasibility spike: Ubuntu-on-WSL2 + CUDA check + weights download + single-GPU serve attempt + VRAM measurement | Go/no-go decision, recorded in a new dated plan doc |
| **Phase 1** | Scaffold repo: AGENTS.md, four SKILL.md files, script stubs with JSON contracts, configs | Structure review |
| **Phase 2** | Implement env-setup path end-to-end (audit → uv env → download → serve → healthcheck) | Healthy local server |
| **Phase 3** | Implement compose-brief (adapted minimax-music-gen protocol + caption-rewriter integration) | First caption from a real interview |
| **Phase 4** | Implement generate-song + judge-quality (metrics + CLAP) | First judged multi-take session |
| **Phase 5** | End-to-end runbook polish, example song session, docs | Full pipeline demo |

## 10. Out of Scope (for now)

- Hosted MiniMax API provider (`mmx` CLI, `music-2.6-free`, covers via `music-cover-free`)
- Playlist/taste-profiling features (`minimax-music-playlist`)
- LLM-as-judge quality stage
- Multi-GPU or remote-server deployment configs

## 11. Open Questions

None blocking. Defaults assumed: 3 seeded takes per generation round; `sessions/` naming =
`YYYYMMDD-HHMMSS-<slug>`; both `oss/` checkouts stay vendored (not submodules).

## Change Log

- 2026-08-23 — Initial version. Captures discussion outcomes D1–D4, asset inventory §4,
  architecture §5, risks §8, roadmap §9.
- 2026-08-23 — Open-sourcing requirement adopted; see
  [2026-08-23-open-source-standards.md](2026-08-23-open-source-standards.md). Where git
  publication is concerned it refines this document's "vendored" wording: `oss/` stays
  local-only (git-excluded) and is reproduced via a pinned fetch script.
