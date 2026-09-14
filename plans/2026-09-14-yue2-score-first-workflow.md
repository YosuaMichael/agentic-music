# YuE2 score-first workflow: plan → review → render

**Date:** 2026-09-14
**Status:** active
**Extends** [plans/2026-09-13-yue2-default-model.md](2026-09-13-yue2-default-model.md).
Amends nothing; it adds a mode to the `yue2` pipeline that the other models do not have.

## 1. Why

YuE2 plans an editable melody-and-chord score (ABC) *before* it renders audio. That plan is
the model's real creative decision, and it is the only place where structure, harmony and
tempo are visible as text. Until now our wrapper threw it away as a by-product of a take:
the only way to see the composition was to pay for a full render first, and a bad plan cost
a full render to discover.

For a model with **no duration control** (decision Y8 — the score *is* the form), reviewing
the plan before rendering is the only cheap way to catch a wrong structure. The repo already
believes in this pattern — compose-brief has a mandatory preview-and-confirm gate, and
`judge-quality` never runs unprompted — so the score deserves the same treatment.

## 2. What was measured before implementing (2026-09-14, RTX 4090, offline)

| Step | Wall time |
|---|---:|
| `--stage plan` (score only, no audio) | **18.4 s** (19.1 s through the dispatcher) |
| Render an approved score | **42.7 s** |
| One-shot (plan + audio) | 54.7 s |

And three properties that make the review gate trustworthy rather than decorative:

1. **The planner is deterministic for a given prompt + seed.** A plan-only run produced a
   `score.abc` byte-identical (`sha256 d3675af6…`) to the score the earlier one-shot take
   had produced.
2. **Rendering an unedited plan reproduces the one-shot song exactly.** Rendered through
   our pipeline, `take-06` is byte-identical to the one-shot `take-02` for WAV, FLAC *and*
   MP3 (matching SHA-256). Approving a plan does not change the music.
3. **An edited score changes the song, and the edit is carried through.** Replacing 25 `"G"`
   chords with `"Em"` produced different audio and a take whose `score.abc` is byte-identical
   to the edited input.

Upstream's own integrity machinery was confirmed too: `SymbolicPlan.load()` reproduced the
take **sample-exactly** (5,176,256 × 2 array equality) and *refused* a tampered plan
("Saved plan changed; supply modified ABC as an external planner input"). That refusal is why
we can detect edits for free — see S3.

## 3. Decisions

### S1 — Plans are first-class artifacts, not takes
- `<session>/plans/plan-NN/` holds the upstream plan bundle verbatim: `score.abc`,
  `plan.json`, `abc_tokens.npy`, `prefix.npy`, `plan_manifest.json`, plus our `generate.log`.
- `<session>/plans/plan-NN.request.json` is the exact request sent, and
  `plans/plan-NN.{style,lyrics}.txt` / `.caption.md` / `.caption.json` are the frozen
  provenance snapshots, mirroring the take convention.
- A plan carries **no audio** and is numbered in its own namespace, so planning never
  consumes a take id. Re-planning retires a previous attempt as `plan-NN_failed` rather than
  deleting it (the repo's existing rule).

### S2 — Two stdout contracts, not one
`--stage plan` emits **`plan/v1`**; audio still emits **`generate/v1`** unchanged. A plan is
not a take and must not masquerade as one, so it does not pretend to have a WAV, an RTF, or
a duration. `plan/v1` carries what a review gate needs without further file reads:
`plan`, `score_abc`, `score_sha256`, `score_lines`, a capped `score_preview`, `plan_json`,
`plan_manifest`, `request`, `truncated`, `elapsed_s`, and a `next` line telling the agent how
to render the approved version.

### S3 — Render through `--abc-file`, and detect edits from the plan manifest
The render supplies the approved score as `--abc-file`, which is upstream's "score-conditioned
generation" path and, as measured, reproduces the planned song byte-exactly. Edit detection
compares the supplied score's SHA-256 against `plan_manifest.json` — the same hash upstream
uses to reject a modified plan — so:
- `score_edited: false` → unedited, and the result says so,
- `score_edited: true` → a new performance of an edited composition,
- `null` → the plan has no manifest to compare against (unknown, never guessed).

A verbatim *copy* of the planned score passed via `--score-file` is correctly reported as
**not** edited, because the comparison is by bytes, not by path.

`SymbolicPlan.load()` (sample-exact, hash-verified reuse) stays documented but unwired: it is
a Python-API path, and our pipeline drives the CLI. It is only stronger in that it also
refuses to render an edited plan, which `--abc-file` handles by design.

### S4 — Score-first is the default `yue2` flow; the user can decline the gate
generate-song plans first (≈19 s), shows the user the score, and asks: **approve / edit /
re-plan with another seed**. Only on approval does it render (≈43 s). If the user says
"just render it", the skill goes straight to the one-shot path — the gate is a default, not a
toll. `minimax-music3` has no plan stage, so `--stage plan` is rejected for it with a precise
message rather than silently doing something else.

### S5 — A take records exactly which score bytes produced it
Take metadata gains `rendered_from: {plan, score_source, score_sha256, plan_score_sha256,
score_edited, seed_overridden}`, and the render's own `score.abc` stays in the take's native
bundle. So any take can be traced back to an approved plan and to the precise composition it
realised — and `--from-plan` defaults its seed and `cot` to the plan's own values, because
rendering a plan at a different seed would silently produce a different song.

### S6 — `--seed` is required except when rendering an approved plan
A plan already fixes its seed; demanding it again invites a mismatch. The dispatcher and the
generator therefore require `--seed` for a new plan or a one-shot take, and take it from
`plan.json` when rendering. An explicit `--seed` that differs is recorded as
`seed_overridden: true` rather than being refused, because a deliberate re-performance at a
new seed is a legitimate experiment — it just must not be silent.

## 4. Bug fixed on the way

Implementing this exposed a real, pre-existing defect: `Runtime.path()` returned `None` for
*any* Windows absolute path in WSL mode, on the theory that host-absolute paths "cannot be
mapped". They can — that is exactly what `/mnt/c/...` is. The consequence was that **any
absolute `--session` path broke** YuE2 generation (and `setup_yue2.py`/`select_model.py`
shared the same helper). Relative session paths had hidden it. All three copies now map
drive-absolute paths onto `/mnt/<drive>`, and the earlier test that had encoded the wrong
behaviour asserts the mapping instead.

## 5. Verification

End to end on the real session `studio/sessions/20260913-233400-yue2-first-song/`:

| Check | Result |
|---|---|
| `--stage plan` → `plan/v1` | ✅ 19.1 s, `plans/plan-01/`, no audio |
| plan score == earlier one-shot score | ✅ `sha256 d3675af6…` |
| `--from-plan` → take | ✅ 42.7 s, `score_edited: false`, explanatory note |
| plan-rendered take == one-shot take | ✅ WAV/FLAC/MP3 byte-identical (`6cddf029…`/`481f288e…`/`fe094e03…`) |
| edited score render | ✅ take-07 different audio, `score_edited: true`, native `score.abc` == the edit |
| verbatim copy via `--score-file` | ✅ `score_edited: false` (byte comparison, not path) |
| provenance in take metadata | ✅ both hashes + `seed_overridden` recorded |
| `cot=off` refused for plan mode | ✅ nothing to review |

Not verified: `cot=melody` planning, and a render with `seed_overridden: true` (both
allowed, neither exercised). `minimax-music3` has no plan mode by construction.

## 6. Rollback

Ignore `--stage plan` / `--from-plan`; the one-shot path is unchanged and still the default
for every model. Session data written by the new mode is additive: `plans/` directories and
`rendered_from` in take metadata are ignored by everything that does not ask for them.
