---
name: judge-quality
description: >
  Score generated takes for a session: objective audio metrics plus CLAP
  text-audio semantic alignment, producing review.json with a ranking and
  verdicts. Use after generate-song produces takes.
scope: >
  Decision D4: automated metrics + CLAP alignment only. No LLM-as-judge pass.
---

# Skill: judge-quality

## Procedure

0. **Learnings check.** Skim `studio/learnings/LEARNINGS.md` (gitignored; if
   missing, treat as empty); apply its rules while
   scoring. This skill runs only when the user opted in after generation.

1. For every `takes/take-*.wav` in the session:

   ```bash
   python scripts/analyze_audio.py --audio <wav>     # analyze_audio/v1
   ```

2. Semantic alignment of prompt vs audio (needs CLAP model on first run,
   ~2 GB download, cached afterwards). **Score each take against the prompt that
   actually produced it**, using that take's own frozen snapshot — a session may
   mix takes rendered from different models and revisions:
   - `yue2` takes → `takes/take-NN.style.txt` (the short style prompt YuE2 read;
     see `metadata.json` → `provider`). CLAP aligns far better against this than
     against a 250–450-word Structured Caption the model never saw.
   - `minimax-music3` takes → `takes/take-NN.caption.md`.
   - Fall back to the root `caption.md` only for legacy takes with no snapshot.

   ```bash
   python scripts/clap_score.py --caption <take-NN.style.txt | take-NN.caption.md> \
                                --audio <wav>         # clap_score/v1
   ```

3. Merge into `studio/sessions/<song-id>/review.json`:

```jsonc
{
  "schema": "review/v1",
  "song_id": "...",
  "takes": [
    {
      "take": "take-01",
      "model": "yue2",
      "prompt_scored": "takes/take-01.style.txt",
      "metrics": { /* analyze_audio/v1 payload */ },
      "clap":    { /* clap_score/v1 payload */ },
      "flags":   ["trailing_silence_gt_2s", ...]
    }
  ],
  "ranking": ["take-02", "take-01", "take-03"],
  "notes": "one line explaining ranking rationale"
}
```

Record `model` (from each take's `metadata.json`) and `prompt_scored` so a
cross-model ranking is interpretable rather than opaque — CLAP scores from a
short `style.txt` and from a long Structured Caption are not directly
comparable, so when a session mixes models, rank within each model and say so
in `notes` instead of pretending the numbers share a scale.

## Flag rules (initial thresholds — tune via dated plan doc, not silently)

| Metric | Flag when |
|---|---|
| `duration_s` | `< 30` (likely truncation) or `> 330` (frame cap exceeded) |
| `peak_dbfs` | `> -0.1` (clipping) |
| `trailing_silence_s` | `> 2.0` |
| `mean_volume_lufs` | deviates more than 12 LU between takes of same session |
| `clap.similarity` | `< 0.20` — weak caption/audio match worth regenerating |

Ranking: fewer flags first, then higher CLAP similarity, then longer duration.

**CLAP is noisy at GPU precision — do not over-read small gaps.** Measured
2026-09-13: two byte-identical takes scored 0.6102 vs 0.6026, and re-scoring one
file three times gave 0.5968 / 0.5820 / 0.5897 — a spread of ~0.015. Treat any
CLAP difference below ~0.02 as noise: rank on flag count first, and when two
takes are within noise, say the alignment difference is not meaningful rather
than declaring a winner on it.

## Presentation contract

Report to the user as a table:
`take | duration | peak dBFS | trailing silence | CLAP | flags`.
Always recommend exactly one take. Offer the minimax-music-gen feedback loop:
**love it / adjust & regenerate / fine-tune via Advanced mode / start over**.
Versioned regeneration keeps prior files untouched (`_vN` suffix rule).
