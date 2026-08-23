---
name: generate-song
description: >
  Generate seeded music takes for a prepared session folder by calling the
  local MiniMax Music 3 endpoint through scripts/generate.py. Use after
  compose-brief has produced caption.md and lyrics.txt and the server is
  healthy.
---

# Skill: generate-song

## Preconditions (verify, don't assume)

1. `sessions/<song-id>/caption.md` and `lyrics.txt` exist.
2. `scripts/serve.py status` reports healthy (run env-setup if not).

## Procedure

1. Read take count + seeds from `configs/provider.toml` (`[generation]`,
   default 3 takes, seeds cycled).
2. **Dispatch takes SEQUENTIALLY** — measured faster than concurrent dispatch
   on single-GPU hosts (see plans/2026-08-23-performance-research.md).
3. For each take, run as a **background job** (non-streaming generation can
   take many minutes):

   ```bash
   python scripts/generate.py --session sessions/<song-id> --seed <seed>
   ```

4. Parse each result's `generate/v1` JSON. On success it names the written
   WAV and its sidecar `metadata.json` (seed, params, request timestamp).
5. Gate: every requested take exists as a non-empty WAV with valid metadata;
   report duration from metadata.

## Cost guidance (from upstream docs)

Wall time scales with `max_new_tokens` (25 frames = 1 second of audio). When
iterating a caption with the user, render **short clips first**
(`--max-new-tokens 300–750`) and only render full length once the style is
approved.

## Failure handling

| Symptom | Action |
|---|---|
| Server unhealthy mid-batch | Stop remaining takes; `serve.py status`; restart if needed; rerun only missing takes |
| Generation exceeds health timeout | Kill job, mark take failed in metadata, retry once |
| Content filter rejection | Report to user with reason; adjust brief/caption via compose-brief |
| Truncated/silent audio | Keep the file, flag it; judge-quality will quantify the defect |

Never delete failed takes — rename with `_failed` suffix so evidence persists.

## Handoff

On completion, invoke `judge-quality` on the session folder, then present the
ranked results table to the user.
