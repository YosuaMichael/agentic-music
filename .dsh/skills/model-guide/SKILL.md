---
name: model-guide
description: >
  Per-model parameter and capability reference for the music models this studio
  can drive: `yue2` (YuE2-3B, default) and `minimax-music3` (audio.cpp GGUF or
  the SGLang-Omni server). Models are deliberately NOT standardised — each keeps
  its own vocabulary, defaults, and limits. Read the section for the session's
  model and call it with its native parameters (via scripts/generate_take.py
  --extra-arg). Use when a take needs a knob the first-class flags do not expose,
  when comparing models, or when deciding which model fits a song.
---

# Skill: model-guide

The models are **not** interchangeable and are **not** normalised behind one
parameter set. Each section below is the truth for that model: its own request
fields, its own CLI flags, its own defaults, and its own limits. Agents are
expected to read the relevant section and drive the model natively — that is the
point of this skill.

## How to use it

1. Read `<session>/model.json` (or `python scripts/select_model.py --session <dir>`)
   to learn which model this song uses. The choice is session state; never change
   it silently.
2. Find that model's section below.
3. Generate through the dispatcher, adding any model-native option with
   `--extra-arg` (repeatable, shell-split):

   ```bash
   python scripts/generate_take.py --session studio/sessions/<id> --seed 7 \
       --extra-arg "--quantization fp8"
   ```

   `--extra-arg` reaches the model's own CLI. Use the attached form for a value
   starting with `--` — `--extra-arg=--quiet`, not `--extra-arg --quiet`, which
   argparse reads as a missing value. It may **not** set the flags that
   carry the session file contract (`--session`, `--seed`, `--config`,
   `--take-id`, `--request`, `--output`, `--id`, `--style`, `--lyrics`, …); those
   are rejected with a message naming the first-class alternative. Everything an
   agent passes is recorded in `takes/take-NN.metadata.json` (`extra_args` /
   `extra_payload`) and in `generate/v1`, so a take never lies about its inputs.
4. The first-class flags every model shares are only: `--session`, `--seed`,
   `--take-id`, `--config`, plus the dispatcher's `--model` override. Beyond
   those, **the models differ** — check before using `--cot`, `--duration-sec`,
   or `--max-new-tokens`, which are each accepted by exactly one backend.

## Pick a model (the ask-once decision, in one table)

| | `yue2` — **default** | `minimax-music3` |
|---|---|---|
| Weights license | **CC BY-NC 4.0 — non-commercial only** | MiniMax-Music3 Community License |
| Instrumentals | ❌ impossible (lyrics required) | ❌ **also impossible** — accepts empty lyrics, then sings anyway |
| Prompt artifact | `style.txt` (short comma list) | `caption.md` (Structured Caption) |
| Editable score | ✅ `score.abc` per take, plus a **review gate**: plan first (≈19 s) → approve or edit → render (≈43 s) — see §1.7 | ❌ |
| Length control | ❌ none — model decides | ✅ `--duration-sec` / `--max-new-tokens` |
| Engines | one (`yue2` CLI, WSL on Windows) | `audiocpp` (Windows-native) or `local` (SGLang server) |
| Measured on this machine | see §1.6 (107.8 s song in 45.5 s model time) | see §2.5 |

**Instrumental-only is unsupported by BOTH models.** YuE2 refuses outright; MiniMax
Music 3 takes the empty-lyrics request and sings anyway — the owner reports this across
many attempts, and three 2026-08-27 studio learnings entries record successively
stronger caption/lyrics strategies all failing. Do not promise an instrumental, and do
not "try a better caption": `[models.*].supports_instrumental` is `false` for both, and
an empty `lyrics.txt` makes the MiniMax generator return a `warnings` entry. The same
audio.cpp runtime does expose other `gen` families (`stable_audio`, `ace_step`,
`heartmula`) as **unverified leads** — see
[plans/2026-09-14-instrumental-generation-unsupported.md](../../../plans/2026-09-14-instrumental-generation-unsupported.md).

Cover versions: neither model is wired for them today (`yue2` *can* do
ABC-conditioned covers upstream; our wrapper blocks `--abc-file` so provenance
stays truthful — wire it as a dated plan change first).

---

## 1. `yue2` — YuE2-3B (default)

**Identity.** `m-a-p/YuE2-3B` (3.63 B params, BF16) + decoder `m-a-p/YuE2-Vae`.
Upstream: [multimodal-art-projection/YuE](https://github.com/multimodal-art-projection/YuE),
pinned at commit `88da114a67df892af0329472073b96a5ef700b93` in `oss/yue2`
(see `docs/upstream.md`). First-party code Apache-2.0; **weights CC BY-NC 4.0**.
Installed into `~/yue2/venv` inside WSL2; weights in `~/yue2/weights` (HF cache).

**Architecture in one line.** One AR–NAR Mixture-of-Transformers predicts an ABC
score + semantic tokens → flow-matching latents → VAE decodes 48 kHz stereo.
Symbolic planning is what makes the score inspectable and editable.

**How it runs here.** `scripts/generate_yue2.py` builds a request JSON, then runs
`yue2 generate --request <take-NN.request.json> --output takes/take-NN.yue2`.
Upstream nests output under the request id, so audio lands at
`takes/take-NN.yue2/take-NN/audio.flac`; we transcode a 48 kHz PCM16 WAV master
plus an MP3 companion and keep the FLAC and the whole native bundle.

### 1.1 Request-level parameters (the model's real interface)

| Field | Default | Range / notes |
|---|---|---|
| `style` | required | Free text: language, genre, instruments, vocal character, tempo. Alias `tags`. Keep it short — it is a descriptor list, not a caption |
| `lyrics` | required | Plain text with `[Verse]`/`[Chorus]`-style section tags. **No instrumental mode exists** |
| `cot` | `full` | `full` (melody + chord plan) · `melody` (melody only; upstream recommends for covers) · `off` (no plan, no score file) |
| `seed` | upstream `831001`; ours cycles `[generation].seeds` | Integer in `[0, 2**63)` |
| `cfg_scale` | unset → `1.0` (`full`/`melody`), `1.01` (`off`) | `[0, 20]`; text guidance. `[yue2].cfg_scale = 0.0` in config means "leave it to upstream" |
| `id` | our take name | Output subdirectory name |
| `abc` / `abc_path` | unset | Supply a score (must be `cot=full` or `melody`). **Blocked by our wrapper for now** |

Unknown request fields raise `ValueError` — upstream allows only those keys
(plus ignored metadata `lang`, `eval_index`, `clip_id`, `prompt`).

### 1.2 Sampling parameters (reachable only via `--config`, not flags)

Defaults: semantic `temperature=1.0, top_p=0.95, top_k=100,
repetition_penalty=1.2, penalty_window=50, min_tokens=200, max_tokens=9000`;
ABC plan `temperature=0.7, top_p=0.9, top_k=30, repetition_penalty=1.005,
penalty_window=100, min_tokens=32, max_tokens=4096`. **`max_tokens` is the length
ceiling** (9000 ≈ 6 minutes) — there is no duration field. Fixed internally:
`ode_steps=32`, `ode_method=midpoint`, `context=24576` (changing them raises).

### 1.3 CLI flags (via `--extra-arg`)

| Flag | Default | Effect |
|---|---|---|
| `--vae` | `standard` | `standard` (listening; **this is YuE2-Vae**) · `legacy` (paper benchmark decoder) · HF repo · local dir |
| `--model` | `m-a-p/YuE2-3B` | HF repo or local directory |
| `--revision`, `--vae-revision` | — | Pin model/VAE versions (reproducibility) |
| `--device` | `auto` | `auto` / `cuda` / `cpu` |
| `--budget` | `24` (GiB) | Per-process memory budget; ≤12 switches the VAE to tiled decode |
| `--backend` | `torch` | `torch` · `torch-eager` · `vllm` (vLLM needs the `fast` extra + H800-class GPU) |
| `--quantization` | `none` | `none` · `fp8` (fp8 disables CUDA graphs) |
| `--offload-ar` | off | Move AR modules to CPU during flow matching (memory tradeoff; needs exclusive model access) |
| `--offline` | off | Never touch the network (`[yue2].offline = true` is our config switch) |
| `--stage` | `audio` | `plan` stops after planning |
| `--quiet` / `--no-progress` | off | Suppress progress output |
| `--resume` | off | Re-validate a **completed** result (never resumes an interrupted run) |

Subcommands: `yue2 doctor [--verify-hashes]`, `yue2 generate`, `yue2 batch
--input <jsonl> --concurrency 1` (concurrency must be 1 on the torch pipeline).

### 1.4 Capabilities

- ✅ Full songs with vocals + accompaniment, 48 kHz stereo, unquantized
- ✅ Symbolic melody/chord plan per take (`score.abc`, `plan.json`) → inspectable, editable
- ✅ Text guidance (`cfg_scale`), separate plan/synthesis/decode APIs
- ✅ Upstream: zero-shot covers and agentic score editing (needs SheetSage2/MERT2 — **not** wired here)
- ✅ Languages: model card tags `zh` + `en`; others unverified
- ❌ Instrumentals · ❌ duration control · ❌ reference audio / phonemes / `bpm` / negative prompt / edit interval (docs state these fields do not exist)
- ⚠️ One request at a time; **24 GB-class GPU + 24 GB host RAM** documented

### 1.5 Gotchas

- `lyrics` is mandatory → an empty `lyrics.txt` is refused by our wrapper (exit 2)
  rather than sent as a broken request. **Instrumental songs are not a MiniMax job
  either** — no shipped model can render one (see the table above).
- `--vae legacy` is *not* a name for the default VAE; `standard` **is** `YuE2-Vae`.
- A non-empty output directory raises upstream — our wrapper retires the previous
  attempt as `take-NN.yue2_failed` instead of deleting it.
- Upstream ships no MP3 writer; our MP3 comes from `scripts/transcode.py`.
- Long lyrics can hit the token ceiling: the take still renders and is flagged
  `"truncated": true` (playable but likely cut short).
- **The plan is the model's own composition.** `style` hints are advisory: in the
  measured session a `92 BPM`/G-major brief produced `Q:1/4=90` in `K:D`. Read
  `score.abc` (or `plan.json`) to see what it actually wrote before blaming the
  prompt.
- The retained `takes/take-NN.yue2/take-NN/generate.log` is the benchmark and
  debugging record: per-stage elapsed times, token throughput, and the model's
  own `{"status": "complete", "truncated": {...}, "seconds": N}` line.

### 1.6 Measured performance (this machine, 2026-09-13)

RTX 4090 (24564 MiB), WSL2 Ubuntu-24.04, `torch==2.10.0`, `--vae standard`,
no quantization, `[yue2].offline = true`. Song: the 107.8 s take in
`studio/sessions/20260913-233400-yue2-first-song/`.

**Headline: a 107.8 s song in 45.5 s of model time (RTF 0.42), 54.7 s end to end.**

| Stage (`generate.log` → `take-NN.yue2/`) | `cot=full` | `cot=off` |
|---|---:|---:|
| Resolving model files | 0.1 s | 0.1 s |
| Verifying model files | 4.7 s | 3.9 s |
| Loading model | 2.4 s | 1.8 s |
| Planning score (ABC) | 10.1 s (1203 tok @ 119/s) | — (no plan) |
| Generating song (semantic) | 21.8 s (2697 tok @ 123.8/s) | 23.8 s (2551 tok @ 107.0/s) |
| Synthesizing audio (32 ODE steps) | 6.8 s | 5.9 s |
| Loading audio decoder | 3.3 s | 3.2 s |
| Decoding audio (VAE, 3 chunks) | 1.0 s | 0.9 s |
| **Model total** | **45.5 s** | **35.8 s** |
| **Our end-to-end** (`generate/v1.elapsed_s`, incl. process start, WAV + MP3 encode) | **54.7 s** | **42.9 s** |
| Audio produced | 107.8 s | 102.0 s |
| **RTF** (model / end-to-end) | 0.42 / 0.51 | 0.35 / 0.42 |
| Peak GPU memory | ~9.3 GiB above a 1.5 GiB idle desktop (11.0 GiB total observed) | same |

Notes that matter when reading the table:

- **`cot=off` is not faster per token.** It skips the 10 s planning stage but its
  default text guidance is 1.01 instead of 1.0, so the CFG branch runs and token
  throughput drops (107 vs 124 tok/s). Planning pays for itself in tokens/s.
- **Offline is not optional.** The same take rendered once online spent **~250 s**
  in "Resolving model files" over ~46 Hugging Face connections — 5× the model work
  — versus 0.1 s offline. That is why `[yue2].offline = true` is the shipped
  default; `setup_yue2.py` is what fetches weights.
- **Reproducible:** the same seed and prompt produced byte-identical WAV, FLAC, and
  MP3 (SHA-256 match) across two runs, one of them online. Same machine + same
  settings ⇒ same bytes.
- Upstream's published reference (3.6-min song, 71 s, 11.18 GiB, 139 tok/s) is
  consistent with these figures; our shorter song yields proportionally less.
- Output level varies by mode: `cot=full` peaked at −1.4 dBFS here, `cot=off` at
  0.0 dBFS (worth a clipping flag in `judge-quality`).

### 1.7 Score-first: plan the composition, approve it, then render

Because YuE2 plans before it renders, and has **no duration control**, the composition is
worth approving *before* paying for audio. This is the default `yue2` flow (plan decision
S4; [plans/2026-09-14-yue2-score-first-workflow.md](../../../plans/2026-09-14-yue2-score-first-workflow.md)).

```bash
# 1. plan only — score, no audio (≈19 s); emits plan/v1
python scripts/generate_take.py --session <dir> --seed 7 --stage plan

# 2. render the approved plan (≈43 s); seed and cot come from the plan
python scripts/generate_take.py --session <dir> --from-plan <dir>/plans/plan-01

# 2b. render an edited composition (never edit the plan's own score in place)
python scripts/generate_take.py --session <dir> --from-plan <dir>/plans/plan-01 \
    --score-file <dir>/plans/plan-01.edited.abc
```

Artifacts: `plans/plan-NN/` (`score.abc`, `plan.json`, `abc_tokens.npy`, `prefix.npy`,
`plan_manifest.json`, `generate.log`), `plans/plan-NN.request.json`, plus frozen
`plans/plan-NN.style.txt` / `.lyrics.txt` snapshots. A plan is **not** a take: no audio, its
own numbering, so planning never consumes a take id. `plan/v1` carries the score, its
SHA-256, a capped `score_preview` ready to show a user, and a `next` hint.

What is guaranteed, all measured (2026-09-14, RTX 4090, offline):

| Property | Evidence |
|---|---|
| The planner is deterministic for a prompt + seed | plan-only `score.abc` byte-identical to the one-shot run's |
| Approving an unedited plan does not change the music | plan-rendered take byte-identical to the one-shot take (WAV/FLAC/MP3) |
| An edit changes the song and is carried through | 25× `"G"`→`"Em"` → different audio, and the take's `score.abc` == the edit |
| Verbatim copies are not mislabelled as edits | edit detection compares bytes against the plan manifest, not paths |
| The plan's integrity is checkable | upstream `SymbolicPlan.load()` reproduced the take sample-exactly and refused a tampered plan |

A take rendered this way records `rendered_from: {plan, score_source, score_sha256,
plan_score_sha256, score_edited, seed_overridden}` in `takes/take-NN.metadata.json`, so any
take traces back to the exact composition bytes it realised. Two limits to keep in mind:
`cot=off` sketches no score at all (`--stage plan` is refused — there is nothing to review),
and `--seed` is required for a plan or one-shot take but comes from `plan.json` when
rendering (an explicitly different seed is recorded as `seed_overridden: true`, never
silent). `SymbolicPlan.load()` (sample-exact reuse) is documented upstream but **not wired**
here — our pipeline drives the CLI.

---

## 2. `minimax-music3` — MiniMax Music 3


**Identity.** `MiniMaxAI/MiniMax-Music3` weights; engine chosen by
`[provider].type`. The same model, two very different engines — and the engine
determines which parameters exist at all.

| | engine `audiocpp` (default) | engine `local` |
|---|---|---|
| Runtime | `.tools/audiocpp/audiocpp_cli.exe` (Windows-native, no server) | SGLang-Omni server in WSL (`scripts/serve.py`) |
| Quantization | Q8 GGUF components (a Q8-as-default hardlink dir) | float32 synthesis + fp8 backbone |
| Parameter surface | CLI flags + `--request-option` | HTTP JSON payload + server-side pipeline YAML |
| Speed (published, ~200 s song) | ≈ 4 min | ≈ 16–19 min |
| Peak VRAM (published) | 16.8 GB | 23.6 GB |

Model-reported capabilities (from `audiocpp_cli.exe --inspect`):
`task=gen`, `modes=offline`, `supports_style_condition=true`,
`supports_speaker_reference=false`, `supports_timestamps=false`, `languages=auto`.

### 2.1 `audiocpp` engine — parameters

Configured in `[audiocpp]`; overridable per take with `--extra-arg
"--request-option <key>=<value>"`.

| Request option | Config default | Notes |
|---|---|---|
| `duration_sec` | `[generation].max_new_tokens / 25` (9000 → 360 s) | Length budget (25 frames = 1 s) |
| `num_inference_steps` | 30 | DiT steps |
| `guidance_scale` | 1.7 | |
| `ar_guidance_scale` | 1.5 | Backbone CFG |
| `top_k` | 50 | |
| `seed` | from `--seed` (cycling `[7, 42, 1234]`) | |

Also reachable generically at the CLI: `--temperature`, `--top-p`,
`--repetition-penalty`, `--do-sample`, `--num-beams`, `--max-tokens`,
`--max-steps`, `--threads`, `--device`, `--log`. Treat these as *unverified* for
this family — the model's own request options above are the ones in use, and the
studio's standing note is that per-token sampling knobs have no effect here. A/B
before believing any of them; record the result in a dated plan document.

Component mixes: `--session-option minimax_music3.<component>_gguf=<file>`
(`language_model_gguf`, `rvq_depth_decoder_gguf`, `flow_transformer_gguf`), and
`--model-dir <dir>` / `[audiocpp].model_dir` for a whole alternative package
(e.g. the q4 mix). Discovery helpers: `--inspect`, `--list-loaders --json`,
`--list-pipelines`.

### 2.2 `local` (SGLang) engine — parameters

Payload keys built by `scripts/generate.py`: `model` (from `[local].model`),
`input` (lyrics), `instructions` (caption), `response_format`, `seed`,
`max_new_tokens` (`[generation].max_new_tokens`), `stream: false`. Extra payload
fields may be added with `--extra-arg KEY=VALUE`. Server-side knobs live in
`configs/music3-pipeline.yaml` (`minimax_music3_ar.runtime.sglang_server_args`),
not in the per-take call.

### 2.3 Capabilities

- ✅ Multilingual (`languages=auto`), style-conditioned via the Structured Caption
- ✅ Length budget (short clip iteration is practical)
- ✅ Offline CLI engine with no Python server
- ❌ **No instrumental mode.** An empty `lyrics.txt` is a request the model ignores: it
  sings anyway. `[models.minimax-music3].supports_instrumental = false`, and the
  generator returns a `warnings` entry when lyrics are empty.
- ❌ No symbolic score / editable composition
- ❌ No speaker reference or timestamps (per `--inspect`)

### 2.4 Gotchas

- The `audiocpp` *release 0.6.1* requires the **default package filenames** to
  exist before it honours component overrides — that is why `setup_audiocpp.py`
  builds a hardlink directory with Q8 content under `*_q4_0.gguf` names. Don't
  "fix" that; it is load-bearing.
- **Don't spend another attempt on instrumental prompting.** Three escalating
  strategies are already recorded as failures (strictly-instrumental caption →
  exclusion repeated in every section → truly 0-byte lyrics with the words
  *singing*/*vocal line* removed). The limit is the model, not the wording.
- `[provider].type = "local"` needs `scripts/serve.py status` healthy first; the
  audiocpp engine needs no server.
- Its caption is model-specific: feeding `style.txt` here (or vice versa) degrades
  output. Each model reads its own artifact.

### 2.5 Measured performance (this machine)

Published/repo figures: ~4 min for a ~200 s song on audio.cpp Q8 at 16.8 GB peak;
**measured on this machine during this session: 5 s clip in 17.0 s** (RTF 3.41,
seed 7, `models/audiocpp/Music3-GGUF-q8asdefault`). The SGLang engine's published
figures are 16–19 min / 23.6 GB — see
[plans/2026-08-23-performance-research.md](../../../plans/2026-08-23-performance-research.md).

---

## 3. Cross-model rules that do not bend

1. **One model per session.** `model.json` is written once and read by every take.
   `--model` on the dispatcher is for a deliberate A/B, and it is recorded as
   `model_source: "flag"`.
2. **Prompt artifacts are per model** — `style.txt` for `yue2`, `caption.md` for
   `minimax-music3`. Both are authored per song; never feed one to the other model.
3. **Provenance is frozen per take**: `take-NN.request.json`, `take-NN.style.txt`,
   `take-NN.caption.md`, `take-NN.lyrics.txt`, `take-NN.caption.json`, plus
   `take-NN.yue2/` (score bundle) for YuE2. Never edit or delete these.
4. **Sequential dispatch.** YuE2 is one-request-at-a-time upstream, and concurrent
   dispatch measured *slower* on a single GPU for MiniMax.
5. **VRAM is shared**: both models cannot generate at once on one GPU. YuE2 peaks
   ~11–14 GiB, the SGLang engine ~24 GiB.
6. **Licence**: YuE2 output is non-commercial (CC BY-NC 4.0 weights). If the user
   needs commercially usable audio, that is `minimax-music3`.

## 4. Where the truth lives

- Wiring and config: `scripts/generate_take.py`, `scripts/generate_yue2.py`,
  `scripts/generate_audiocpp.py`, `scripts/generate.py`, `configs/provider.toml`
- Upstream model interfaces: `oss/yue2/README.md`, `oss/yue2/docs/generation.md`,
  `oss/yue2/src/yue2/cli.py`, `oss/yue2/skills/yue2-music/SKILL.md` (pinned checkout)
- Discovery commands: `yue2 doctor`, `yue2 --help`, `audiocpp_cli.exe --help`,
  `audiocpp_cli.exe --inspect`, `python scripts/select_model.py --list`
