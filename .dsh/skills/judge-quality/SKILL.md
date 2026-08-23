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

1. For every `takes/take-*.wav` in the session:

   ```bash
   python scripts/analyze_audio.py --audio <wav>     # analyze_audio/v1
   ```

2. Semantic alignment of caption vs audio (needs CLAP model on first run,
   ~2 GB download, cached afterwards):

   ```bash
   python scripts/clap_score.py --caption studio/sessions/<song-id>/caption.md \
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
      "metrics": { /* analyze_audio/v1 payload */ },
      "clap":    { /* clap_score/v1 payload */ },
      "flags":   ["trailing_silence_gt_2s", ...]
    }
  ],
  "ranking": ["take-02", "take-01", "take-03"],
  "notes": "one line explaining ranking rationale"
}
```

## Flag rules (initial thresholds — tune via dated plan doc, not silently)

| Metric | Flag when |
|---|---|
| `duration_s` | `< 30` (likely truncation) or `> 330` (frame cap exceeded) |
| `peak_dbfs` | `> -0.1` (clipping) |
| `trailing_silence_s` | `> 2.0` |
| `mean_volume_lufs` | deviates more than 12 LU between takes of same session |
| `clap.similarity` | `< 0.20` — weak caption/audio match worth regenerating |

Ranking: fewer flags first, then higher CLAP similarity, then longer duration.

## Presentation contract

Report to the user as a table:
`take | duration | peak dBFS | trailing silence | CLAP | flags`.
Always recommend exactly one take. Offer the minimax-music-gen feedback loop:
**love it / adjust & regenerate / fine-tune via Advanced mode / start over**.
Versioned regeneration keeps prior files untouched (`_vN` suffix rule).
