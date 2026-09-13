# AGENTS.md — agentic-music Agent Operating Manual

You are an autonomous coding agent working in **agentic-music**: a repository whose purpose
is to let agents like you set up, run, and iterate on **fully local music generation** with
open-weights models — **YuE2** (the default model) and **MiniMax Music 3** — end to end,
following written instructions — not improvisation.

## Two Workspaces

This repository has two distinct contexts:

- **Creating songs?** Work inside the [`studio/`](studio/) workspace — its
  [`studio/AGENTS.md`](studio/AGENTS.md) is a lean creator manual, and songs
  live in `studio/sessions/<song-id>/`. Do not read development plans there.
- **Developing the repository?** You are in the right place; continue below.

## Read Order (do not skip)

1. [`plans/INDEX.md`](plans/INDEX.md) — decision history index; read every `active` document.
2. [`plans/2026-08-23-initial-plan.md`](plans/2026-08-23-initial-plan.md) — objective,
   decisions D1–D4, architecture, risks, roadmap.
3. [`plans/2026-08-23-open-source-standards.md`](plans/2026-08-23-open-source-standards.md) —
   licensing policy, hard publication rules, engineering standards.

Decisions recorded in `active` plan documents are binding. To change one, write a new dated
plan document and register it in the index — never silently contradict them.

## Operating Principles

1. **State lives in files, not chat.** All per-song state is under
   `studio/sessions/<song-id>/`. Any agent must be able to resume by reading that folder alone.
2. **Agents orchestrate; scripts execute.** Infra steps (audit, env, download, serve,
   generate, analyze) go through `scripts/` CLIs with documented JSON output. Never
   freehand curl/python/pip for those steps. If a script is missing a capability, add it
   to the script — then use it.
3. **JSON contracts are interfaces.** Each script's docstring defines its stdout JSON
   schema (`<name>/vN`). Changing a schema is a breaking change: bump the version, update
   dependent skills, note it in `CHANGELOG.md`.
4. **Long operations run as managed background jobs** with health checks; never block a
   session interactively on multi-minute downloads or generations when the harness offers
   background jobs.

## Hard Rules (open-source hygiene)

1. NEVER `git add` anything under `oss/`, `studio/sessions/`, `models/`, `.venv/`,
   `.tools/` — they are gitignored; verify with `git status` before committing.
2. Never copy content out of `oss/minimax-music3/` into committed files (no license found
   upstream → all rights reserved). Reference paths, fetch at runtime via
   `scripts/fetch_upstream.sh`. Adapted text from MIT-licensed sources carries a header
   comment naming origin + license. (`oss/yue2` is Apache-2.0, so copying would be
   permitted with attribution — we still don't: we invoke upstream's CLI instead of
   vendoring it.)
3. No API keys, tokens, telemetry, or machine-specific absolute paths in committed files.
   For the YuE2 runtime use `~`/repo-relative paths in `[yue2]` (`~` is expanded inside
   the runtime).
4. This project is independent; never imply MiniMax or YuE2-authors affiliation in
   user-facing text.
5. **YuE2 model weights are CC BY-NC 4.0 — non-commercial only.** Since `yue2` is the
   default model, the default pipeline path inherits that restriction. Never describe
   YuE2 output as commercially usable; the MiniMax Music 3 engine is the alternative when
   commercial use matters.

## Repository Map

```
AGENTS.md            ← you are here (developer manual)
plans/               dated, indexed plan documents (decision history)
.dsh/skills/         the five skills — DSH-native discovery root (compose-brief ·
                     generate-song · judge-quality · env-setup · model-guide)
scripts/             deterministic JSON-out CLIs (the only way infra happens)
configs/provider.toml  music-model registry + engine endpoint/defaults
studio/              song-creation workspace: studio/AGENTS.md + studio/sessions/
docs/upstream.md     pinned upstream revisions + digests (generated)
oss/                 git-excluded upstream checkouts created by fetch_upstream.sh
```

## The Pipeline

```
compose-brief      choose model once → interview user → brief.md + lyrics.txt
                   → style.txt (YuE2) + $music-caption-rewriter → caption.md
generate-song      model.json + prompt + lyrics → N seeded takes
                   → takes/take-NN.wav (+ metadata.json), via scripts/generate_take.py
judge-quality      metrics + CLAP alignment → review.json (ranked verdict)
env-setup          once per machine: audit → model runtime setup → healthcheck
```

Run `env-setup` first on a fresh machine. Then loop compose-brief → generate-song →
judge-quality, presenting ranked results to the user between iterations.

## Music models vs engines (two axes — do not conflate them)

| Axis | Values | Set where | Changed by |
|---|---|---|---|
| **Model** (what generates music) | `yue2` (default), `minimax-music3` | `<session>/model.json`, default in `[models].default` | the user, asked once per song by compose-brief |
| **Engine** (how MiniMax Music 3 runs) | `audiocpp` (default), `local` | `[provider].type` | the owner, repo-wide |

Dispatch goes through `scripts/generate_take.py` — the backend generators
(`generate_yue2.py`, `generate_audiocpp.py`, `generate.py`) are only invoked directly by
the env-setup smoke tests, which deliberately bypass any session's model choice. `yue2`
requires `style.txt` (short prompt) and its weights are **CC BY-NC 4.0 (non-commercial)**;
`minimax-music3` uses `caption.md` instead. See
[plans/2026-09-13-yue2-default-model.md](plans/2026-09-13-yue2-default-model.md).

**Instrumental-only is unsupported by BOTH models** (`supports_instrumental = false` for
every registry entry). YuE2 refuses outright; MiniMax Music 3 accepts empty lyrics and
sings anyway, which cost the owner repeated failed attempts. Say so before spending GPU
time — never promise an instrumental and never try another prompt formula. See
[plans/2026-09-14-instrumental-generation-unsupported.md](plans/2026-09-14-instrumental-generation-unsupported.md).

## Session Protocol

Song id format: `YYYYMMDD-HHMMSS-<slug>`. Artifacts are fixed names (see initial plan §7).
Never rename artifacts mid-session; superseded takes stay in place with `_vN` suffixes.
Root `lyrics.txt` / `style.txt` / `caption.md` are the canonical *working* copies; each
generation also freezes per-take provenance snapshots (`takes/take-NN.style.txt`,
`take-NN.caption.md`, `take-NN.lyrics.txt`, `take-NN.caption.json`, and for YuE2 the
`take-NN.request.json` + `take-NN.yue2/` score bundle) — treat those as immutable history.
`model.json` is session state: never hand-edit it, and never re-ask once it exists.

## Platform Notes

- **Default music model (since 2026-09-13): YuE2** (`yue2`). Linux-only upstream,
  so on Windows it runs in the `Ubuntu-24.04` WSL distro. Machine setup:
  `python scripts/setup_yue2.py`; generation: `python scripts/generate_take.py`.
  Its weights are CC BY-NC 4.0 → non-commercial only.
- **MiniMax Music 3 engine default (since 2026-08-23): audio.cpp GGUF CLI**
  (Windows-native, no WSL needed for generation). Machine setup:
  `python scripts/setup_audiocpp.py`. Its engine is selected by
  `[provider].type`; see plans/2026-08-23-audiocpp-gguf-provider.md.
- The SGLang-Omni reference stack (path B) runs inside the `Ubuntu-24.04`
  WSL distro; invoke via:
  `wsl.exe -d Ubuntu-24.04 -u root -- bash -lc '<command>'`
  Start/stop it with `python scripts/serve.py run|status|stop` from Windows.
- SGLang weights live inside the WSL filesystem (`~/models/minimax-music3`);
  YuE2's venv and weights live there too (`~/yue2/venv`, `~/yue2/weights`);
  audio.cpp GGUFs live under `<repo>/models/audiocpp/` — all gitignored.
- `[yue2]` paths in config use `~` (expanded inside the runtime), so the committed
  config stays machine-independent.

## Current Status

**v0.0.1 released (tagged 2026-08-23).** MiniMax Music 3 generation is validated
end to end on a single RTX 4090 (audio.cpp GGUF default; SGLang-Omni remains the
"local" reference path). Phase 0 gate PASSED (GO-WITH-LIMITS) — see
[plans/2026-08-23-phase0-single-gpu-spike.md](plans/2026-08-23-phase0-single-gpu-spike.md)
for measurements and the exact working config
([configs/music3-pipeline.yaml](configs/music3-pipeline.yaml)). First song generated and
judged in `studio/sessions/20260823-105740-first-light/`.

**YuE2 added 2026-09-13 as the default model** (session-scoped ask-once choice) and
**verified end to end**: setup green, four real takes rendered and judged
(`studio/sessions/20260913-233400-yue2-first-song/`), 107.8 s song in 45.5 s of model time
(RTF 0.42), ~9.3 GiB peak — see
[plans/2026-09-13-yue2-default-model.md](plans/2026-09-13-yue2-default-model.md) §5.1.
**Corrected 2026-09-14:** instrumental-only is unsupported by *both* models, not just
YuE2 — see
[plans/2026-09-14-instrumental-generation-unsupported.md](plans/2026-09-14-instrumental-generation-unsupported.md).
Roadmap: an instrumental-capable `gen` family, CI workflow.
