# YuE2 as a second music model — session-scoped model choice, default `yue2`

**Date:** 2026-09-13
**Status:** active
**Supersedes nothing.** Extends decision D1's provider axis with a second, orthogonal
axis: *which music model*, separate from *which engine runs MiniMax Music 3*.

## 1. Why

The owner asked to enable the new **YuE2** model
([multimodal-art-projection/YuE](https://github.com/multimodal-art-projection/YuE),
tagline *"Unifying Symbolic and Audio Music Generation at Frontier Quality"*) alongside the
existing MiniMax Music 3 pipeline: the user picks the model at the start of a song, YuE2 is
the default, and the question is asked **once**.

YuE2 was released 2026-09-12 and is a different kind of system from Music 3, not just a
better checkpoint: it writes an **editable symbolic plan** (melody + chords as ABC) before
rendering audio, and the same checkpoint does zero-shot covers and agentic score editing.

### 1.1 Evidence gathered (upstream primary sources, 2026-09-13)

| Fact | Value | Source |
|---|---|---|
| Model | `m-a-p/YuE2-3B` — 3 630 684 224 params BF16, single 7.26 GB `model.safetensors`, AR–NAR Mixture-of-Transformers + flow-matching latents + VAE | [model card](https://huggingface.co/m-a-p/YuE2-3B) |
| Decoder | `m-a-p/YuE2-Vae` (530 MB, default listening) / `YuE2-Vae-legacy` (benchmark protocol) | same |
| Weight download | ≈ **7.8 GB** total (model + VAE), **not gated**, no click-through | HF API `gated: false` |
| Quality (WildSongBench, 192 prompts, SongBench Avg ↑) | **YuE2 6.7316** / YuE2 best-of-8 6.9632 vs **MiniMax Music 3 6.2830**, Suno v5 6.8721 | [README benchmarks](https://github.com/multimodal-art-projection/YuE#benchmarks) |
| Text alignment (MuLan ↑ / AllMusicCaps ↑) | YuE2 0.5068 / 0.4054 vs Music 3 0.3928 / 0.3609 | same |
| Speed on RTX 4090, `cot="full"` | **71.0 s** for a 214.9 s song (RTF ≈ 0.33; VAE decode 3.6 s) | model card, *Speed and resources* |
| Peak VRAM on RTX 4090 | **11.18 GiB** (max-context test 14.08 GiB); 24 GB host RAM | same |
| Output | 48 kHz stereo FLAC `PCM_24`, no quantization, `ode_steps=32`, context 24576 | same + `pyproject.toml` |
| Dependencies | pure-Python + pinned wheels (`torch==2.10.0`, `transformers==4.57.6`, `huggingface-hub==0.36.2`, `soundfile`); attention falls back flash→cuDNN→SDPA. **No `flash-attn`, Triton or other compiled extension**, and no `ffmpeg` needed | upstream `pyproject.toml`, `cuda_graph.py`, `modeling_yue2.py` |
| CLI | console script `yue2` with `doctor` / `generate` / `batch`; `yue2 generate --request <json> --output <dir>`; `--vae` takes `standard|legacy|<repo>|<dir>` (not an HF id by default) | upstream `src/yue2/cli.py` |
| Architecture of the change | another *engine* had to be added, not a config flag flipped | — |

For comparison, the current default (audio.cpp Q8 GGUF) renders a ~200 s song in ≈4 min at
16.8 GB peak (`plans/2026-08-23-performance-research.md`). YuE2 is therefore both
**~3.4× faster** and **~5.6 GB lighter** on the same GPU, while scoring ~0.45 SongBench
higher than Music 3. That is the justification for making it the default.

### 1.2 Constraints that shaped the design

| Constraint | Consequence |
|---|---|
| Upstream supports **Linux** only (Windows untested/unsupported) | Windows hosts run YuE2 through the existing WSL2 `Ubuntu-24.04` runtime, exactly like the SGLang-Omni reference path (decision D1 path B) |
| Requires **BF16 GPU + 24 GB VRAM** and **24 GB host RAM**; one song at a time | Meets D1's RTX 4090 bar; must never run concurrently with the SGLang server |
| Model weights are **CC BY-NC 4.0** (non-commercial); first-party code is Apache-2.0 | Hard guardrail, see Y6 |
| Install is **source-first** (`pip install .`); the README's wheel fallback is v0.1.6 | Install from the pinned checkout; wheel is an explicit opt-in fallback |
| Pure-Python install, but pinned heavy wheels (`torch==2.10.0`) | Setup is a long background job — same discipline as `env-setup` path B |
| `style` is a **short comma-separated prompt**, not a 250–450-word Structured Caption | New session artifact `style.txt` (decision Y5) |
| A pipeline call produces **one candidate**; candidate selection is a separate step | Maps cleanly onto our existing seeded-take model: one take = one call = one seed |
| CLI writes `<output>/<request-id>/` and raises on a non-empty target dir | Failure evidence is preserved by renaming to `*_failed`, and retries start fresh (Y7) |
| **`lyrics` is a required field; there is no instrumental mode** | Instrumentals are a hard, early failure on this backend, never a silent misrender (Y9) |
| **No duration/length parameter exists** — length is emergent from `semantic_sampling.max_tokens` (default 9000 ≈ 6 min ceiling) | Documented limitation; the `--duration-sec` / `--max-new-tokens` knobs do not carry over (Y8) |
| Request JSON rejects unknown fields (`ValueError`) | The wrapper emits only the documented keys: `id`, `style`, `lyrics`, `cot`, `seed` (+ `cfg_scale`) |
| The `yue2-v0.1.6` **release archive** states first-party code is CC BY-NC 4.0, while the git `main` source is Apache-2.0 | Install from the pinned **checkout**, not the archive wheel; wheel is an opt-in fallback only (Y4) |

## 2. Decisions

### Y1 — YuE2 becomes the default music model
`configs/provider.toml` gains a model registry:

```toml
[models]
default = "yue2"
available = ["yue2", "minimax-music3"]
```

`[provider].type` (`"audiocpp"` | `"local"`) is **unchanged in meaning**: it still selects the
*engine* that runs MiniMax Music 3, and is consulted only when the session's model is
`minimax-music3`. This keeps decision D1's owner-approved audio.cpp default intact for
anyone who picks Music 3.

### Y2 — The model is chosen once per song session, and that choice is session state
- The question is asked by **compose-brief**, at the start of a session, *once*.
- The answer is recorded in `studio/sessions/<song-id>/model.json` (`model_choice/v1`).
- Every later step (generate-song, judge-quality) **reads** that file. If it exists, the
  question is never asked again — that is the whole point of "ask first once".
- If the user has no preference, the recorded choice is the registry default (`yue2`) with
  `"source": "default"`; if they chose explicitly, `"source": "user"`.
- `scripts/select_model.py` owns this file. It also reports **availability** per model, so
  the ask can be honest about what is actually installed on this machine.

Rationale for session state rather than a global setting: operating principle 1 (state lives
in files) and the `studio/` workspace rule that creation agents must not edit `configs/`.
A per-session file also makes a session reproducible and lets a session be re-rendered with
the other model later without touching global config.

### Y3 — Model ≠ engine
The two axes are orthogonal and both live in config:

| Axis | Values | Where | Changed by |
|---|---|---|---|
| Model (what generates music) | `yue2`, `minimax-music3` | session `model.json`, default from `[models].default` | the user, once per session |
| Engine (how Music 3 runs) | `audiocpp`, `local` | `[provider].type` | the owner, repo-wide |

### Y4 — YuE2 runtime: WSL on Windows, native on Linux
Following the path B precedent, YuE2's venv and weights live in the **Linux** filesystem, not
on the `/mnt/c` repo mount (9p is slow and the weights are large):

```toml
[yue2]
runtime = "wsl"          # "wsl" (Windows host) | "native" (Linux host)
wsl_distro = "Ubuntu-24.04"
wsl_user = "root"
src_dir = "oss/yue2"     # repo-relative pinned checkout (fetch_upstream.sh)
venv_dir = "~/yue2/venv" # runtime-home paths, `~` resolved inside the runtime
weights_dir = "~/models/yue2"
```

The upstream checkout stays the single source of truth and **is never committed**
(`oss/` is gitignored; hard rule 1). `scripts/setup_yue2.py` installs *from* it with
`pip install <checkout>`, which is upstream's documented quick-start path and the one their
own agent skill recommends.

`install_source = "wheel"` is available as an explicit fallback that installs the pinned
`yue2-v0.1.6` release wheel instead. Prefer the checkout: the release body for that archive
declares first-party code **and** weights CC BY-NC 4.0, whereas the git source is Apache-2.0
with only the weights non-commercial (Y6). Recorded here because it is a licensing
difference, not just a packaging preference.

Weights (≈7.8 GB, not gated) are fetched with `hf download` into `HF_HOME = weights_dir`;
generation then uses upstream defaults and never passes `--vae m-a-p/YuE2-Vae` — upstream's
`--vae` takes `standard | legacy | <path> | <repo>`, and `standard` is already the default
listening decoder.

### Y5 — New artifact: `style.txt`
YuE2's `style` is a short descriptor prompt — upstream's example is
`"English, warm piano pop, expressive female voice, acoustic piano, rounded bass and light
drums, lyrical memorable melody, unhurried phrasing, 88 BPM"`. Feeding it our 250–450-word
Music-3 Structured Caption would be well off-distribution and would burn style-conditioning
capacity on prose the model was not trained to read.

Therefore **compose-brief emits both prompt artifacts** from the same interview:

| Artifact | Consumer | Shape |
|---|---|---|
| `caption.md` + `caption.json` | MiniMax Music 3 (as today) | 3 headings, ~250–450 words |
| `style.txt` | YuE2 | one line, comma-separated: language, genre, vocal character, 2–3 instruments, tempo/feel |

Both derive from the same brief; neither contains lyric text. For `minimax-music3` sessions
`style.txt` is optional; for `yue2` sessions it is **required** (with a documented fallback
to `caption.json.inputs.description` for legacy sessions, reported as
`"style_source": "caption.json"` so it is visible that the prompt was degraded).

### Y6 — Licence guardrail (binding)
YuE2 **weights** are **CC BY-NC 4.0 — non-commercial only**; the repository code is
Apache-2.0. Consequences:

1. Making `yue2` the default means the default path requires **non-commercial** weights. The
   ask-once prompt states this inline, and `[models.yue2]` carries
   `commercial_use = false` so tooling can surface it.
2. README, NOTICE and the model registry all state the restriction. No commercial-use
   claim may be made about YuE2 output without the owner obtaining separate terms.
3. No upstream content is copied into committed files. We reference the checkout path and
   invoke upstream's own CLI; nothing from the YuE repo is vendored. Our wrapper is
   original code under this repo's MIT licence.
4. The repo's own code licence stays MIT.

### Y7 — Provenance for YuE2 takes
`generate-song` already freezes per-take inputs. YuE2 adds a machine-readable request and the
symbolic artifacts, because they are the model's real interface:

```
takes/take-NN.wav                  # PCM master, 48 kHz stereo (judging/playback)
takes/take-NN.flac                 # upstream lossless original
takes/take-NN.mp3                  # shareable companion (as today)
takes/take-NN.metadata.json        # generate_meta/v1 + provider "yue2"
takes/take-NN.request.json         # EXACT request sent (id/style/lyrics/cot/seed)
takes/take-NN.style.txt            # frozen style prompt snapshot
takes/take-NN.caption.md/.json     # frozen as today
takes/take-NN.yue2/                # upstream native artifacts: score.abc, plan.json,
                                   # result.json, latent.npy, timings, model identities
```

The ABC score is retained deliberately: it is what makes the score editable afterwards
(future plan) and it is the evidence of what the model actually composed.

Failure handling follows the existing `_failed` convention: upstream refuses a non-empty
output directory, so a retry of the same take id renames the old evidence directory to
`take-NN.yue2_failed` and starts fresh rather than deleting it.

### Y8 — No duration knob on the YuE2 backend (documented limitation)
Upstream exposes **no length or duration parameter**. Duration is emergent from
`semantic_sampling.max_tokens` (default 9000 ⇒ ≈6 min ceiling) and the hard
`prefix + max_tokens ≤ 24576` context check. Sampling/steps are reachable only through
`--config <json>`.

Consequences: the skill's "render short clips first" cost guidance does **not** apply to
YuE2, and `--duration-sec` / `--max-new-tokens` are not accepted by
`scripts/generate_yue2.py`. This is an accepted trade-off, not a gap to paper over: a full
3.6-minute song costs ~71 s on the target GPU, so clip-first iteration buys little here. An
empty `[yue2].extra_generate_args` list is the documented escape hatch for anyone who needs
to pass `--config`/`--quantization`/`--offload-ar` deliberately.

### Y9 — Instrumentals are a hard, early failure on YuE2
> **CORRECTED 2026-09-14.** This decision also claimed `minimax-music3` *can* render
> instrumentals, and that instrumentals were therefore a "MiniMax-only" job. The owner
> reports — and three 2026-08-27 learnings entries corroborate — that MiniMax Music 3
> never produced an instrumental-only song either. **Neither model supports
> instrumental-only.** See
> [plans/2026-09-14-instrumental-generation-unsupported.md](2026-09-14-instrumental-generation-unsupported.md).
> The YuE2-specific content below still stands.

Upstream requires `lyrics` (missing ⇒ `ValueError("Provide style and lyrics")`) and has no
instrumental mode. ~~Our studio supports instrumentals via a 0-byte `lyrics.txt`.~~
**Withdrawn 2026-09-14:** a 0-byte `lyrics.txt` only *asks* MiniMax Music 3 for an
instrumental, and it sings anyway; no shipped model renders instrumentals.

Therefore:
1. `[models.yue2]` declares `supports_instrumental = false`; the original claim that
   `[models.minimax-music3]` declares `true` is **withdrawn** — it is `false` too, so
   `select_model.py` reports no instrumental-capable model at all.
2. compose-brief's ask-once step no longer offers a model for instrumentals; Step 0 states
   the limitation before any work begins.
3. `generate_yue2.py` refuses an empty/whitespace-only `lyrics.txt` with exit 2 and an
   actionable message — never a silently wrong render.

### Y10 — `[yue2].offline` defaults to `true`
Measured (see §5.1): an online run spent **~250 s** resolving/revalidating already-present
weights over ~46 HF connections, versus 0.1 s offline — 5.5× the total wall time of the
same take. Since `setup_yue2.py` is the component that fetches weights, generation has no
reason to talk to the network. `offline = false` is therefore an explicit opt-in for
"deliberately re-check the hub", not the default. A missing-weights failure now surfaces as
an offline resolution error naming the remedy (`python scripts/setup_yue2.py`).

### Y11 — Models stay unstandardised, and agents drive them natively
The models differ in prompt artifact, parameter vocabulary, capabilities and length
semantics. Rather than normalising them behind one lowest-common-denominator interface:

1. A **`model-guide` skill** documents each model's own request fields, CLI flags,
   defaults, capabilities, limits and measured performance, plus the ask-once decision
   table. It explicitly states that the models are not interchangeable.
2. The dispatcher and all three generators accept repeatable **`--extra-arg`**, which
   reaches the model's own CLI (or payload, for the HTTP engine). Model-native knobs are
   therefore reachable without a code change.
3. Only flags that carry the **session file contract** are reserved: they would otherwise
   relocate output, renumber takes, or desynchronise the frozen `take-NN.request.json`
   from what the model actually received. Everything passed is recorded in
   `take-NN.metadata.json` (`extra_args` / `extra_payload`).

This keeps `generate_take.py` as the one place that knows *which* model runs, while the
*how* stays per-model and agent-driven.

## 3. Scope

**In scope (this document):** model registry, ask-once session state, YuE2 setup script,
YuE2 generation script, model dispatch, skill/docs/CI updates.

**Explicitly out of scope (future dated plan):** zero-shot covers and audio-to-score
transcription (SheetSage2/MERT2 — separate environments with conflicting pins), agentic
ABC score editing, `yue2 batch`, the H800/vLLM server path, and quantized YuE2.

## 4. Risks

| Risk | Mitigation |
|---|---|
| The pinned `torch==2.10.0` wheel may be unavailable for Windows, and CUDA-graph capture under WDDM is unverified — upstream is Linux-only-validated | YuE2 therefore runs inside WSL2, where upstream's own CI and quick start are validated; `yue2 doctor` is a mandatory setup gate and `native`/WSL is a config axis, not a code fork |
| The install is a multi-GB `torch` download and can fail slowly | Setup runs as a managed background job with explicit gates; a pinned wheel fallback (`install_source = "wheel"`) exists |
| WSL not present on a Windows host | Availability probe reports `ready: false` with the exact remedy; the ask-once prompt then surfaces MiniMax Music 3 as the ready alternative rather than failing later |
| 24 GB host RAM requirement unmet | Recorded as a setup gate note (host RAM is not asserted as a hard failure because WSL reports host RAM inconsistently) |
| Non-commercial weights used commercially | Y6 guardrail, surfaced in prompt + docs + registry metadata |
| Language coverage: model card tags `zh`/`en` | Documented; non-tagged languages are unverified rather than claimed |
| Two models disagree on prompt shape | Y5 `style.txt` keeps each prompt native to its model; nothing is silently reused across models |
| Instrumental request against a backend that cannot render it | Y9 hard guard in the generator + registry metadata + ask-once caveat |
| Re-running setup after an upstream bump breaks the runtime | The upstream checkout is pinned by `fetch_upstream.sh` and recorded in `docs/upstream.md` |

## 5. Verification status

**Verified end to end on this machine (2026-09-13).** `python scripts/setup_yue2.py`
returned `setup_yue2/v1` with `ok: true`, `ready_for_generation: true`,
`installed_version: 0.1.6`, both weight repos present, CUDA visible in WSL, and
`doctor_ok: true` reporting exactly the pinned upstream stack (torch 2.10.0,
transformers 4.57.6, huggingface-hub 0.36.2, safetensors 0.7.0, tiktoken 0.12.0,
soundfile 0.13.1). Three real takes were then rendered through
`python scripts/generate_take.py` into
`studio/sessions/20260913-233400-yue2-first-song/` — see §5.1.

Also verified in this change: script contracts (`select_model/v1`, `setup_yue2/v1`,
`generate_yue2/v1`, dispatcher pass-through), unit tests, ruff.

### 5.1 Measured benchmark (RTX 4090, WSL2 Ubuntu-24.04, no quantization)

| | `cot=full` | `cot=off` |
|---|---:|---:|
| Model pipeline total | **45.5 s** | 35.8 s |
| Our end-to-end (`elapsed_s`) | **54.7 s** | 42.9 s |
| Audio produced | 107.8 s | 102.0 s |
| RTF (model / end-to-end) | 0.42 / 0.51 | 0.35 / 0.42 |
| Peak GPU memory | ~9.3 GiB above idle (11.0 GiB total observed) | same |

Stage detail (`cot=full`): resolve 0.1 s · verify 4.7 s · load model 2.4 s ·
**plan 10.1 s** (1203 tok @ 119/s) · **semantic 21.8 s** (2697 tok @ 123.8/s) ·
synthesis 6.8 s (32 ODE steps) · decoder load 3.3 s · VAE decode 1.0 s.

Two findings this benchmark produced, both now fixed or documented:

1. **Online generation was 5.5× slower than offline**: 299.5 s vs 54.7 s for the
   same take, because the first run spent ~250 s in "Resolving model files" over
   ~46 Hugging Face connections revalidating 7.8 GB of already-present weights.
   `[yue2].offline = true` is now the shipped default (setup is what fetches).
2. **Same seed ⇒ byte-identical WAV, FLAC and MP3** (SHA-256 match), even across
   one online and one offline run — seeded takes are reproducible on this machine.

Reproduce with:

```bash
python scripts/setup_yue2.py                     # once per machine
python scripts/generate_take.py \
  --session studio/sessions/20260913-233400-yue2-first-song --seed 7
```

**Still unverified:** `cot=melody` and ABC-conditioned covers (the wrapper blocks
`--abc-file` on purpose), `yue2 batch`, the fp8 quantization path, and the vLLM
backend. Upstream's own advice applies: anything not measured here is unmeasured.

## 6. Rollback

Set `[models].default = "minimax-music3"` in `configs/provider.toml`. No session data,
weights or scripts need to change; `[yue2]` and all YuE2 artifacts become inert. The
per-session `model.json` files keep old sessions faithful to what actually produced them.
