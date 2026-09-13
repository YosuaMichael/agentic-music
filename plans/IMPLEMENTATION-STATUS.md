# Implementation Status

Living checklist tracking which plan commitments are implemented and verified.
Update the `Status` and `Evidence` columns whenever an item lands; do not
restate history here — dated plan documents remain the decision record.

Statuses: ✅ done · 🟨 partial · ⬜ todo · 🚫 intentionally out of scope

Last updated: 2026-08-23

## Pipeline Phases (initial plan §9)

| Item | Status | Evidence |
|---|---|---|
| Phase 0 — single-GPU feasibility spike | ✅ | GO-WITH-LIMITS verdict, VRAM measurements: [plans/2026-08-23-phase0-single-gpu-spike.md](2026-08-23-phase0-single-gpu-spike.md) |
| Phase 1 — scaffold (AGENTS.md, 4 skills, script contracts, configs) | ✅ | [AGENTS.md](../AGENTS.md), [`.dsh/skills/`](../.dsh/skills/), [`scripts/`](../scripts/), [configs/provider.toml](../configs/provider.toml); studio workspace added later (see below) |
| Phase 2 — env-setup end-to-end on real machine | ✅ | `env_setup/v1` `"ok": true`; healthy server (`serve/v1` healthy) |
| Phase 3 — compose-brief interview → caption | ✅ | Session artifacts: `studio/sessions/20260823-105740-first-light/{brief,caption}.md` |
| Phase 4 — generate-song + judge-quality | ✅ | 3 judged takes + `review.json` in same session folder |
| Phase 5 — CI workflow, packaging polish, publish checklist | 🟨 | pyproject + ruff + pytest done; GitHub Actions workflow not yet added |

## Decisions (D1–D4)

| Decision | Status | Notes |
|---|---|---|
| D1 single RTX 4090 local-only inference | ✅ validated | Works with hybrid precision config (see below); hosted API unused |
| D2 agent-neutral AGENTS.md + skills | ✅ implemented | No harness-specific code committed |
| D3 uv for Python environments | ✅ implemented | WSL venv via env_setup.sh; Windows dev tasks via `uv run`/`uvx` |
| D4 judging = audio metrics + CLAP | ✅ implemented | `analyze_audio.py` + `clap_score.py`; LLM-judge remains out of scope |

## Quality configuration

| Item | Status | Evidence |
|---|---|---|
| Single-GPU serving recipe | ✅ | [configs/music3-pipeline.yaml](../configs/music3-pipeline.yaml): both stages on gpu 0, two processes |
| Audio-quality fix (float32 synthesis + fp8 AR backbone) | ✅ owner-confirmed by listening | A/B evidence: [plans/2026-08-23-quality-regression-fix.md](2026-08-23-quality-regression-fix.md) |
| Decode CUDA graphs re-enabled | ✅ | −12.5% wall time, byte-identical output; capture verified — [plans/2026-08-23-performance-research.md](2026-08-23-performance-research.md) |
| Concurrent take dispatch | ❌ tested, rejected | Slower on single GPU (115 s vs ≈87 s for 3 takes); keep sequential |
| `cache_dit` acceleration option | 🚫 rejected | Upstream: trades audio quality for speed |
| audio.cpp GGUF alternative provider (Q8) | ✅ **default for MiniMax Music 3** | Owner-approved A/B: ~4× faster full songs, −29% peak VRAM — [plans/2026-08-23-audiocpp-gguf-provider.md](2026-08-23-audiocpp-gguf-provider.md) |
| YuE2 as a second music model, `yue2` default | ✅ verified end to end | `setup_yue2.py` → `ok/ready_for_generation: true`, v0.1.6, weights present, CUDA visible, `doctor` green; 3 real takes in `studio/sessions/20260913-233400-yue2-first-song/`; `select_model.py` / `generate_yue2.py` / `generate_take.py` + registry in [configs/provider.toml](../configs/provider.toml) — [plans/2026-09-13-yue2-default-model.md](2026-09-13-yue2-default-model.md) §5 |
| YuE2 measured speed (RTX 4090) | ✅ | 107.8 s song in **45.5 s** model time (RTF 0.42), **54.7 s** end to end, ~9.3 GiB peak; per-stage table in §5.1. `cot=off`: 35.8 s / RTF 0.35. Same seed ⇒ byte-identical WAV/FLAC/MP3 |
| YuE2 offline-by-default (`[yue2].offline = true`) | ✅ | Online revalidation cost ~250 s (5.5× the take): 299.5 s online vs 54.7 s offline for the same seed — plan decision Y10 |
| Per-model capability reference (no standardisation) | ✅ | [`model-guide`](../.dsh/skills/model-guide/SKILL.md) skill: per-model request fields, CLI flags, defaults, capabilities, limits, measured performance; `--extra-arg` passthrough on the dispatcher and all three generators — plan decision Y11 |
| YuE2 `cot=melody`, ABC covers, `batch`, fp8, vLLM | ⬜ | Explicitly out of scope for now; `--abc-file` is blocked by the wrapper on purpose |

| Session-scoped model choice, asked once | ✅ | `scripts/select_model.py` (`select_model/v1`): `needs_choice` gate, recorded choices never re-asked or silently overwritten; compose-brief Step 0b |
| `style.txt` prompt artifact for YuE2 | ✅ | compose-brief Outputs + Step 3a; consumed by `generate_yue2.py` (falls back to `caption.json.inputs.description`, flagged as degraded) |
| YuE2 weight-licence guardrail (CC BY-NC 4.0) | ✅ | `[models.yue2].commercial_use = false` surfaced in the ask-once prompt; README + NOTICE; plan decision Y6 |
| Release v0.0.1 | ✅ tagged 2026-08-23 | First release: local single-GPU pipeline + dual provider support |
| Harness web integration Phase 1 (artifact sidecar + MP3) | ✅ | [scripts/serve_artifacts.py](../scripts/serve_artifacts.py) verified (Range/index/traversal); `transcode.py` companions — [plans/2026-08-23-harness-web-integration.md](2026-08-23-harness-web-integration.md) |
| Loudness normalization pass before delivery | ⬜ | Takes peak at 0 dBFS (matches upstream reference behavior) |

## Repository & Community (open-source standards addendum)

| Item | Status | Evidence |
|---|---|---|
| LICENSE (MIT) | ✅ | [LICENSE](../LICENSE) |
| README with hardware requirements + credits/disclaimer | ✅ | [README.md](../README.md) |
| CONTRIBUTING / CODE_OF_CONDUCT / SECURITY / CHANGELOG / NOTICE | ✅ | repo root |
| .gitignore excluding oss/, sessions/, models/, .venv/ | ✅ | [.gitignore](../.gitignore) |
| GitHub issue + PR templates | ✅ | `.github/` |
| Pinned upstream fetch + digest verification | ✅ | [scripts/fetch_upstream.sh](../scripts/fetch_upstream.sh), [docs/upstream.md](upstream.md) — YuE2 added as a third pin; **docs/upstream.md regenerates on the next run** (it is generated output, never hand-edited) |
| Upstream pin re-check for license change (addendum §9.2) | ⬜ | Re-run at next pin bump |
| caption-rewriter offline fallback in compose-brief | ✅ | [skills/compose-brief/SKILL.md](../.dsh/skills/compose-brief/SKILL.md) Step 3 manual path |
| Machine-readable `caption.json` artifact | ✅ | compose-brief Outputs contract |
| `agents/openai.yaml` metadata for all skills | ✅ | `skills/*/agents/openai.yaml` (agent-ecosystem portability) |
| Contribute templates back upstream | ⬜ | Upstream maintenance section invites additions; needs upstream license clarity first |
| Secret-scan pre-commit hook | ⬜ | Standards addendum §5 — land with CI |
| GitHub Actions CI (ubuntu+windows: ruff, pytest) | ⬜ | Phase 5 |
| Project name finalized | ✅ | `agentic-music` @ github.com/YosuaMichael/agentic-music |
| v0.1.0 release tag after publish checklist | ⬜ | Includes dry-run clone test, license header sweep |

## Deliberately out of scope (unchanged)

🚫 Hosted MiniMax API provider · cover mode (`music-cover-free`) ·
playlist/taste-profiling features · LLM-as-judge stage · multi-GPU/remote configs
