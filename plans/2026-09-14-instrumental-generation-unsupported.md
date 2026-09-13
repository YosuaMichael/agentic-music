# Correction: instrumental-only generation is unsupported by BOTH shipped models

**Date:** 2026-09-14
**Status:** active
**Amends** decision **Y9** in
[plans/2026-09-13-yue2-default-model.md](2026-09-13-yue2-default-model.md), which
recorded `minimax-music3` as the model to use for instrumentals
(`supports_instrumental = true`). That was wrong. Y9's other content — that YuE2 refuses
an empty `lyrics.txt` with a hard failure — stands.

**Also affects** the `instrumental` branch of the intent-detection decision tree in
[plans/2026-08-23-initial-plan.md](2026-08-23-initial-plan.md) §6: that branch cannot be
fulfilled by any shipped model, so it is now a "say so and offer options" path rather than
a generation path.

## 1. What was believed, and what is true

Y9 assumed the split was:

| Model | Instrumental? |
|---|---|
| `yue2` | ❌ upstream requires `lyrics` |
| `minimax-music3` | ✅ 0-byte `lyrics.txt` + a "pure instrumental, no vocals" caption |

**The owner reports that MiniMax Music 3 never produced an instrumental-only song either**,
across many attempts. The repository's own studio memory corroborates this: three separate
learnings entries from 2026-08-27 record the same failure escalating strategy by strategy —

- `pure-instrumental-still-sang` — sang despite an instrumental brief; the caption's single
  "strictly instrumental" mention was overridden.
- `empty-lyrics-for-pure-instrumental` — still sang after the exclusion was repeated in
  Global Metadata, Vocal Details and every Arrangement section.
- `fully-empty-lyrics-and-no-singing-word` — humming persisted even with truly 0-byte lyrics
  and the words "singing"/"vocal line" removed.

Three failed strategies, each with a stronger prompt, is evidence of a **model capability
limit, not a prompting problem**. The correct response is to stop promising instrumentals,
not to write a fourth strategy.

## 2. Decisions

### I1 — Neither model supports instrumental-only. Record it as unsupported.
`[models.yue2].supports_instrumental = false` (unchanged) **and**
`[models.minimax-music3].supports_instrumental = false` (corrected). No shipped model
renders a song without vocals, so the studio has **no instrumental path at all**, and
`select_model.py` reports that to every caller.

### I2 — The studio must say so before doing the work, never after the GPU time.
compose-brief handles an instrumental request at Step 0, before the interview and before
the model question, by telling the user plainly that neither model can do it and offering
the three honest options:

1. render anyway, accepting that vocals will very likely appear (the model gets a say);
2. make it a vocal song instead, which is what both models are actually for;
3. not use this studio for it today (see I4).

The old behaviour — proceeding silently with a 0-byte `lyrics.txt` and a
"pure instrumental" caption — burned the user's time and produced a sung result. That is
the specific failure this document exists to prevent.

### I3 — The 0-byte `lyrics.txt` convention stays, relabelled and instrumented.
It remains the mechanism by which an instrumental is *requested* from `minimax-music3` (the
pipeline and its caption contract expect it), but it is documented as *an attempt that
usually fails*, not as a supported mode. Two machine-visible guards make it impossible to
forget:

- `scripts/generate_audiocpp.py` now emits `"warnings": [...]` and records
  `warnings` in take metadata whenever `lyrics.txt` is empty or whitespace/BOM-only, so a
  caller reports the known limitation instead of silently delivering vocals.
- `scripts/generate_yue2.py` keeps its hard refusal (exit 2, no GPU time spent), with a
  message corrected to stop pointing the user at MiniMax as an alternative.

### I4 — Leads for real instrumental support (unverified, future dated plan)
`audiocpp_cli.exe --list-loaders --json` shows the same runtime can host other `gen`
families besides `minimax_music3`:

| Family | Why it is a plausible instrumental path | Status |
|---|---|---|
| `stable_audio` | Stable Audio is a text-to-music/sound model with no vocal pathway | unverified |
| `ace_step` | ACE-Step is an open text-to-music model with instrumental support | unverified |
| `heartmula` | another open `gen` family | unverified |

These are **leads, not claims**: none is downloaded, configured, benchmarked or listened to
here. Adding one is a real feature (new family config, its own prompt shape, its own
licence review) and belongs in its own dated plan document. Recorded here so the next agent
does not re-litigate MiniMax prompting.

## 3. Consequences

- The ask-once question in compose-brief no longer offers a model for instrumentals; it
  states the limitation and asks how to proceed.
- `generate-song`'s preconditions and failure table no longer route instrumentals to
  `minimax-music3`.
- judge-quality's low-CLAP flag is the closest thing to a leak detector; there is no
  vocal-presence check, so judging an intended instrumental will not tell you reliably
  whether vocals appeared. Not solved here.

## 4. Verification

Locked in as tests, not just prose: the registry must report
`supports_instrumental == false` for **every** entry in `[models].available`, and
`generate_audiocpp.py` must warn on empty/BOM-only lyrics. Docs updated:
`model-guide`, `compose-brief`, `generate-song`, `studio/AGENTS.md`, root `AGENTS.md`,
`README.md`, `CHANGELOG.md`, `plans/IMPLEMENTATION-STATUS.md`.

Not verified: that `stable_audio` / `ace_step` / `heartmula` actually render acceptable
instrumentals on this machine — no new model was installed.
