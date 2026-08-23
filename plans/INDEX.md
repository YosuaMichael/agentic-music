# Plan Documents Index

All planning documents live in this folder. Every plan document is indexed here, by date.

## Conventions

- **Naming:** `YYYY-MM-DD-<slug>.md` — the filename date must match the document's creation
  (or major revision) date.
- **Register:** every new plan document must add a row to the table below on the day it is
  created. Never delete rows; superseded documents get status `superseded` and link to
  their successor.
- **Statuses:** `draft` → `active` → `superseded`. Decisions locked in an `active`
  document are binding until superseded by a newer dated document.

## Index

| Date | Document | Title | Status |
|------|----------|-------|--------|
| 2026-08-23 | [2026-08-23-initial-plan.md](2026-08-23-initial-plan.md) | Initial plan: objective, decisions D1–D4, architecture, upstream asset inventory, risks, roadmap | active |
| 2026-08-23 | [2026-08-23-open-source-standards.md](2026-08-23-open-source-standards.md) | Open-source addendum: MIT license, licensing analysis, upstream fetch strategy, community files, engineering standards, CI | active |
| 2026-08-23 | [2026-08-23-phase0-single-gpu-spike.md](2026-08-23-phase0-single-gpu-spike.md) | Phase 0 gate: pre-registered criteria and measurements for single-GPU serving attempt | active |
| 2026-08-23 | [2026-08-23-quality-regression-fix.md](2026-08-23-quality-regression-fix.md) | Root cause and fix for bf16 synthesis artifacts: hybrid float32 DiT/DAV + fp8 AR config | active |
| 2026-08-23 | [2026-08-23-performance-research.md](2026-08-23-performance-research.md) | Speed/memory research: cookbook facts, decode-graphs adoption (+12.5%), concurrency rejected, quality knobs kept off | active |
| 2026-08-23 | [2026-08-23-audiocpp-gguf-provider.md](2026-08-23-audiocpp-gguf-provider.md) | audio.cpp GGUF provider evaluation: install, integration, benchmarks vs SGLang (in progress) | active |
| 2026-08-23 | [2026-08-23-harness-web-integration.md](2026-08-23-harness-web-integration.md) | Phase 1 artifact sidecar (serve_artifacts.py + Tailscale Serve) and MP3 companions; Phase 2 native plugin sketched | active |
| — | [IMPLEMENTATION-STATUS.md](IMPLEMENTATION-STATUS.md) | Living implementation tracker (not a dated plan doc; updated in place as items land) | tracking |
