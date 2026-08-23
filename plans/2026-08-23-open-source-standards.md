# Open-Source Standards Addendum

| | |
|---|---|
| **Date** | 2026-08-23 |
| **Status** | active |
| **Index** | [plans/INDEX.md](INDEX.md) |
| **Amends** | [2026-08-23-initial-plan.md](2026-08-23-initial-plan.md) |

## 1. Objective

The repository will be published as an open-source project. This addendum defines the
licensing analysis, publication rules, community files, and engineering standards that the
scaffold (Phase 1 onward) must follow. Guiding rule: **open-source-ready from the first
commit** — retrofitting license hygiene after content accumulates is painful and risky.

Decision recorded 2026-08-23: **repository code is licensed MIT**, per owner's choice.
Copyright line uses `agentic-music contributors`; replace with the preferred name/handle at
publish time.

## 2. Licensing Analysis & Policy

| Content | License status | Publication policy |
|---|---|---|
| Our code, skills, docs | Original work | **MIT** (`LICENSE` at repo root) |
| `oss/skills/` collection (incl. `minimax-music-gen`) | MIT © 2026 MiniMax | Adaptation permitted with attribution; credit in README credits + `NOTICE`. Do not bulk-commit the checkout. |
| `oss/minimax-music3/` repo content (incl. `music-caption-rewriter` + its ~1 000 templates) | **No license found in checkout** → all rights reserved by default | **Never committed or copied into our repo.** Referenced only; fetched locally by script (§3). |
| MiniMax-Music3 model weights | Community license on Hugging Face | Never stored in repo; each user downloads via env-setup skill. Personal/local use OK per current reading; re-verify before commercial claims. |
| Generated audio (`sessions/**`) | User-created content | Gitignored by default (privacy); sanitized samples may be added under `examples/` with explicit consent. |

**Hard rules for agents (enforced via AGENTS.md):**
1. Never `git add` anything under `oss/`, `sessions/`, `models/`, `.venv/`.
2. Any adapted third-party text carries a header comment naming origin + license.
3. No API keys, tokens, or machine-specific absolute paths in committed files (pure-local
   design means the project should need zero secrets — keep it that way).

## 3. Upstream Fetch Strategy (replaces "vendored" wording)

The initial plan described `oss/` as "vendored". For the public repo this is refined to
**locally fetched, git-excluded, pinned**:

- New deterministic script `scripts/fetch_upstream.sh`:
  - clones `MiniMax-AI/MiniMax-Music3` and the MiniMax skills collection into `oss/`,
  - checks out the exact commits recorded in `docs/upstream.md`,
  - verifies recorded SHA-256 digests of the small set of files we actually depend on
    (skill SKILL.md, prompt_guide.md, genre-router.md),
  - idempotent; JSON status output like every other script.
- `docs/upstream.md` — human-readable record: upstream URLs, pinned commit hashes,
  digest list, date pinned, why each pin was chosen.
- `oss/` is listed in `.gitignore`; a fresh clone + `fetch_upstream.sh` reproduces the
  development state exactly.
- Benefit beyond licensing: public repo stays lean (~no 1 000-file template library), and
  upstream updates become explicit, reviewable pin bumps.

## 4. Community Files (scaffolded in Phase 1)

| File | Standard / content notes |
|------|--------------------------|
| `LICENSE` | MIT, copyright `agentic-music contributors` |
| `README.md` | Badges · one-paragraph pitch ("agent-executable local music studio") · **hardware requirements stated up front** (single CUDA GPU ≥24 GB class; two-GPU caveat documented) · quickstart · architecture diagram · FAQ · credits & non-affiliation disclaimer |
| `CONTRIBUTING.md` | Dev setup (uv), ruff + pytest gates, how to run the pipeline, agent-contributor welcome section pointing at AGENTS.md |
| `CODE_OF_CONDUCT.md` | Contributor Covenant v2.1 (standard text) |
| `SECURITY.md` | How to report issues; note that pure-local design minimizes attack surface |
| `CHANGELOG.md` | Keep-a-Changelog format, starting v0.1.0 |
| `NOTICE` | Third-party attribution: MiniMax skills (MIT), MiniMax Music 3 references (unlicensed — referenced not redistributed), CLAP/LAION mention |
| `.gitignore` | `oss/`, `sessions/`, `models/`, `.venv/`, `__pycache__/`, `.env`, generated audio |
| `.github/ISSUE_TEMPLATE/` | `bug_report.md`, `feature_request.md` |
| `.github/PULL_REQUEST_TEMPLATE.md` | Checklist: tests, docs, no secrets, no vendored content |

## 5. Engineering Standards

- **Packaging:** `pyproject.toml` managed by `uv`; scripts importable + runnable as CLIs.
- **Quality gates:** `ruff` (format + lint), `pytest`, type hints on all `scripts/`.
- **Contracts:** every script documents its JSON output schema at the top of its docstring;
  schemas are the interface agents rely on, so changes are breaking changes.
- **Versioning:** SemVer; Conventional Commits recommended (not enforced).
- **Pre-commit:** config with ruff + a secret-scan hook (e.g. detect-secrets class) once CI lands.

## 6. Continuous Integration

GitHub Actions workflow (Phase 5): matrix **ubuntu-latest + windows-latest** running
`ruff check`, `ruff format --check`, `pytest`. GPU-dependent integration tests stay manual/
local — CI validates the deterministic-script layer only.

## 7. Positioning & Attribution

- Independent community project — **not affiliated with or endorsed by MiniMax**; say so
  explicitly in README.
- Credits section links both upstream repos and describes exactly what we take from each
  (interaction protocol adapted from MIT-licensed `minimax-music-gen`; caption workflow
  delegates to the publicly-documentated but unlicensed `music-caption-rewriter` which users
  fetch themselves).
- Project name: TBD before publishing (`agentic_music` is the working directory name).
  GitHub org/account: TBD.

## 8. Roadmap Impact (amends initial plan §9)

| Phase | Change |
|-------|--------|
| Phase 1 | Scaffold includes ALL community files from §4 + `.gitignore` + AGENTS.md hard rules (§2) |
| Phase 2 | Add `scripts/fetch_upstream.sh` + `docs/upstream.md`; env-setup skill runs it before caption work |
| Phase 5 | Add CI workflow; tag v0.1.0 release; publish checklist (name, org, license headers, secret scan, dry-run clone test) |

## 9. Remaining Open Items

1. Project name and GitHub location — needed only at publish time.
2. Confirm `music-caption-rewriter`'s upstream repo has not since gained a license that
   permits direct redistribution (would simplify §3; re-check at each pin bump).

## Change Log

- 2026-08-23 — Initial version. MIT chosen for repo code; upstream fetch strategy replaces
  vendoring; community files, engineering standards, CI, and roadmap amendments defined.
