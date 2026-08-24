---
name: generate-song
description: >
  Generate seeded music takes for a prepared session folder through the
  configured provider in configs/provider.toml ([provider].type):
  "audiocpp" (default — audio.cpp GGUF CLI, no server) or "local"
  (SGLang-Omni server via scripts/serve.py). Use after compose-brief has
  produced caption.md and lyrics.txt.
---

# Skill: generate-song

## Preconditions (verify, don't assume)

1. All four artifacts exist NON-EMPTY on disk — verify by listing the session
   folder itself, never by trusting earlier write results (a merged/dropped
   tool invocation can silently lose a file): `brief.md`, `lyrics.txt`,
   `caption.md`, `caption.json`.
2. Read `[provider].type` from `configs/provider.toml`:
   - `"audiocpp"` (default): `.tools/audiocpp/audiocpp_cli.exe` exists
     (run `python scripts/setup_audiocpp.py` if not). No server needed.
   - `"local"`: `scripts/serve.py status` reports healthy (run env-setup if not).

## Procedure

1. **Learnings check.** Skim `studio/LEARNINGS.md` (small, append-only) before
   dispatching anything; its rules override habit.
2. **Ask the user how many takes** (offer the configured default from
   `[generation].num_takes`, usually 3; one take is fine for caption
   iteration). Seeds cycle from `[generation].seeds`. Only proceed with the
   number the user confirmed — never assume.
3. **Dispatch takes SEQUENTIALLY** — measured faster than concurrent dispatch
   on single-GPU hosts (see plans/2026-08-23-performance-research.md).
4. For each take, run as a **background job**:

   ```bash
   # type = "audiocpp" (default)
   python scripts/generate_audiocpp.py --session studio/sessions/<song-id> --seed <seed>

   # type = "local"
   python scripts/generate.py --session studio/sessions/<song-id> --seed <seed>
   ```

5. Parse each result's `generate/v1` JSON. On success it names the written
   WAV and its sidecar `metadata.json`. audiocpp results carry additive
   fields (`provider`, `rtf`, and `mp3`/`mp3_bytes` when the MP3 companion
   is enabled — it is by default).
6. Gate: every requested take exists as a non-empty WAV with valid metadata.
7. **Report quick facts, then STOP and ask about judging.** Present a compact
   table per take: audio duration, generation wall time (elapsed_s), RTF,
   MP3 size (and the player link when the artifact server runs). Then ask:
   *"Run auto-judgement (metrics + CLAP ranking) on these takes?"* — invoke
   `judge-quality` only after an explicit yes. If declined, close with the
   player/download links and offer another generation round instead.

## Learnings protocol

When the user corrects a mistake, or a take/session goes wrong in a way the
skill did not anticipate: append a dated entry to `studio/LEARNINGS.md`
(Symptom / Cause / Rule) in the same turn — do not defer it. Rules there
override habit on every future session.

## Dispatch hygiene & lost-job recovery

A malformed or merged tool invocation can echo a job id while nothing
actually registers — the take then sits "pending" forever while the GPU idles.
Guard against it:

1. **One tool call per invocation.** Never merge a background dispatch with
   any other call in a single block.
2. **Verify liveness before reporting an ETA.** After every dispatch:
   - reading the job must NOT answer `unknown job`; and
   - within ~60 s, either `nvidia-smi` shows high GPU utilization with the
     expected VRAM footprint, or fresh files appear under `<session>/takes/`.
3. **Recovery protocol** when liveness fails (unregistered id, idle GPU, no
   new files after ~5 min): re-list jobs to confirm the loss, relaunch the
   identical command as a NEW background job, then repeat step 2. Never leave
   the session waiting on an id that shows no evidence of running.

## Cost guidance

Wall time scales with length budget (25 frames = 1 second of audio;
`--max-new-tokens` on local / `--duration-sec` on audiocpp). When iterating a
caption with the user, render **short clips first**
(`--max-new-tokens 300–750` ≈ `--duration-sec 12–30`) and only render full
length once the style is approved.

## Failure handling

| Symptom | Action |
|---|---|
| Server unhealthy mid-batch | Stop remaining takes; `serve.py status`; restart if needed; rerun only missing takes |
| Generation exceeds health timeout | Kill job, mark take failed in metadata, retry once |
| Content filter rejection | Report to user with reason; adjust brief/caption via compose-brief |
| Truncated/silent audio | Keep the file, flag it; judge-quality will quantify the defect |
| Job id `unknown` / GPU idle after dispatch | Dispatch was silently lost: relaunch as a fresh background job and verify GPU utilization before reporting any ETA |

Never delete failed takes — rename with `_failed` suffix so evidence persists.

## Handoff

After the user confirms auto-judgement, invoke `judge-quality` on the session
folder and present the ranked results table. If they declined judging, close
with the player/download links and offer: another generation round (new
seeds/count), caption edits via compose-brief, or done.
