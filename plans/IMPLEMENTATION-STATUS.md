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
| Phase 1 — scaffold (AGENTS.md, 4 skills, script contracts, configs) | ✅ | [AGENTS.md](../AGENTS.md), [`skills/`](../skills/), [`scripts/`](../scripts/), [configs/provider.toml](../configs/provider.toml) |
| Phase 2 — env-setup end-to-end on real machine | ✅ | `env_setup/v1` `"ok": true`; healthy server (`serve/v1` healthy) |
| Phase 3 — compose-brief interview → caption | ✅ | Session artifacts: `sessions/20260823-105740-first-light/{brief,caption}.md` |
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
| Decode CUDA graphs re-enabled for speed | ⬜ | Blocked earlier by missing nvcc; nvcc now installed — experiment queued |
| `cache_dit` acceleration option | ⬜ | Untested upstream knob |
| Loudness normalization pass before delivery | ⬜ | Takes peak at 0 dBFS (matches upstream reference behavior) |

## Repository & Community (open-source standards addendum)

| Item | Status | Evidence |
|---|---|---|
| LICENSE (MIT) | ✅ | [LICENSE](../LICENSE) |
| README with hardware requirements + credits/disclaimer | ✅ | [README.md](../README.md) |
| CONTRIBUTING / CODE_OF_CONDUCT / SECURITY / CHANGELOG / NOTICE | ✅ | repo root |
| .gitignore excluding oss/, sessions/, models/, .venv/ | ✅ | [.gitignore](../.gitignore) |
| GitHub issue + PR templates | ✅ | `.github/` |
| Pinned upstream fetch + digest verification | ✅ | [scripts/fetch_upstream.sh](../scripts/fetch_upstream.sh), [docs/upstream.md](upstream.md) |
| Upstream pin re-check for license change (addendum §9.2) | ⬜ | Re-run at next pin bump |
| caption-rewriter offline fallback in compose-brief | ✅ | [skills/compose-brief/SKILL.md](../skills/compose-brief/SKILL.md) Step 3 manual path |
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
