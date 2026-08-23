# AGENTS.md — agentic-music Agent Operating Manual

You are an autonomous coding agent working in **agentic-music**: a repository whose purpose
is to let agents like you set up, run, and iterate on **fully local music generation** with
the open-weights **MiniMax Music 3** model, end to end, following written instructions —
not improvisation.

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
   `sessions/<song-id>/`. Any agent must be able to resume by reading that folder alone.
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

1. NEVER `git add` anything under `oss/`, `sessions/`, `models/`, `.venv/` — they are
   gitignored; verify with `git status` before committing.
2. Never copy content out of `oss/minimax-music3/` into committed files (no license found
   upstream → all rights reserved). Reference paths, fetch at runtime via
   `scripts/fetch_upstream.sh`. Adapted text from MIT-licensed sources carries a header
   comment naming origin + license.
3. No API keys, tokens, telemetry, or machine-specific absolute paths in committed files.
4. This project is independent; never imply MiniMax affiliation in user-facing text.

## Repository Map

```
AGENTS.md            ← you are here
plans/               dated, indexed plan documents (decision history)
skills/              env-setup · compose-brief · generate-song · judge-quality
scripts/             deterministic JSON-out CLIs (the only way infra happens)
configs/provider.toml  endpoint + generation defaults
sessions/<song-id>/  per-song state: brief.md, lyrics.txt, caption.md, takes/, review.json
docs/upstream.md     pinned upstream revisions + digests
oss/                 git-excluded upstream checkouts created by fetch_upstream.sh
```

## The Pipeline

```
compose-brief      interview user → brief.md + lyrics.txt → $music-caption-rewriter → caption.md
generate-song      caption + lyrics → N seeded takes → takes/take-NN.wav (+ metadata.json)
judge-quality      metrics + CLAP alignment → review.json (ranked verdict)
env-setup          once per machine: audit → WSL/uv env → fetch upstream → weights → serve → healthcheck
```

Run `env-setup` first on a fresh machine. Then loop compose-brief → generate-song →
judge-quality, presenting ranked results to the user between iterations.

## Session Protocol

Song id format: `YYYYMMDD-HHMMSS-<slug>`. Artifacts are fixed names (see initial plan §7).
Never rename artifacts mid-session; superseded takes stay in place with `_vN` suffixes.

## Platform Notes

- Development host is Windows with WSL2. The inference stack (SGLang-Omni) runs inside the
  `Ubuntu-24.04` distro; invoke via:
  `wsl.exe -d Ubuntu-24.04 -u root -- bash -lc '<command>'`
- Model weights live inside the WSL filesystem (`~/models/minimax-music3`) for I/O speed;
  they are never inside the repo tree.
- Generated audio lands in WSL, then gets copied into `sessions/<song-id>/takes/` on the
  repo side so it joins the file-based state.

## Current Status

Phase 0 gate PASSED (GO-WITH-LIMITS): MiniMax Music 3 serves and generates on a
single RTX 4090 via colocated two-process topology — see
[plans/2026-08-23-phase0-single-gpu-spike.md](plans/2026-08-23-phase0-single-gpu-spike.md)
for measurements and the exact working config
([configs/music3-pipeline.yaml](configs/music3-pipeline.yaml)). End-to-end
pipeline validated: first song generated and judged in
`sessions/20260823-105740-first-light/`. Roadmap phases 1–2 complete; 3–5
polish items remain (CI, packaging polish).
