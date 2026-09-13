---
name: generate-song
description: >
  Generate seeded music takes for a prepared session folder. The music model is
  the one recorded in the session's model.json (yue2 by default; minimax-music3
  otherwise) and dispatch is by scripts/generate_take.py — never by hand-picking
  a backend script. Use after compose-brief has produced style.txt and
  lyrics.txt.
---

# Skill: generate-song

## Preconditions (verify, don't assume)

1. All artifacts exist on disk — verify by listing the session folder itself,
   never by trusting earlier write results (a merged/dropped tool invocation
   can silently lose a file):
   - `brief.md`, `style.txt` must be non-empty (style.txt is the prompt the
     default model reads);
   - `lyrics.txt` must exist and be non-empty for vocal songs. An **empty**
     `lyrics.txt` means an instrumental attempt: no shipped model can do
     instrumental-only, so confirm the user accepted that (compose-brief Step 0)
     before spending GPU time, and expect a `warnings` entry in the result;
   - `caption.md` / `caption.json` must be non-empty *only* for
     `minimax-music3` sessions.
2. **Music model — ask once, then never again:**

   ```bash
   python scripts/select_model.py --session studio/sessions/<song-id>
   ```

   - `needs_choice: false` → use `chosen.model` as-is. Do not ask.
   - `needs_choice: true` → compose-brief was skipped: ask the user once
     (default `yue2`, see compose-brief Step 0b for the exact question and the
     non-commercial-weight caveat), then record it with `--model <id>`.
   - If `chosen.model` is a model whose `ready` is not `true`, say so before
     dispatching and name its `details.remedy` (`python scripts/setup_yue2.py`
     or `python scripts/setup_audiocpp.py`). Never switch models silently.
3. Readiness of the backend itself is the generator's job to report; a missing
   runtime comes back as a precise `generate/v1` error, not a hang.

## Procedure

1. **Learnings check.** Skim `studio/learnings/LEARNINGS.md` (small, append-only,
   gitignored — if missing, treat as empty) before dispatching anything; its
   rules override habit.
2. **Dispatch 1 take by default** (next seed from `[generation].seeds`; if the
   user explicitly requested N before starting, honor it). One take keeps
   iteration fast/cheap — batch more only after hearing the first result.
3. **Dispatch takes SEQUENTIALLY** — measured faster than concurrent dispatch
   on single-GPU hosts (see plans/2026-08-23-performance-research.md), and YuE2
   is explicitly one-request-at-a-time upstream.
4. For each take, run as a **background job** — one command, whichever model is
   recorded; the dispatcher resolves model → generator:

   ```bash
   python scripts/generate_take.py --session studio/sessions/<song-id> --seed <seed>
   ```

   `generate/v1` comes back with additive `model`, `model_source`
   (`session` | `default` | `flag`) and `generator` fields. For a deliberate
   one-off A/B across models, pass `--model <id>`; per-backend knobs are
   forwarded only where they exist (`--cot` for yue2, `--duration-sec` for
   audiocpp, `--max-new-tokens` for the SGLang path) and are rejected with a
   precise message otherwise.
5. Parse each result's `generate/v1` JSON. On success it names the written
   WAV and its sidecar `metadata.json`. Results carry additive provider fields
   (`provider`, `rtf`, `mp3`/`mp3_bytes`; `cot` and `truncated` on yue2 takes).
   The generator also snapshots the exact prompt inputs into per-take copies
   (`take-NN.style.txt`, `take-NN.caption.md`, `take-NN.lyrics.txt`,
   `take-NN.caption.json`) — provenance survives later revisions, so never
   edit or delete those per-take copies. A yue2 take additionally keeps its
   native upstream artifacts in `takes/take-NN.yue2/` (`score.abc`, `plan.json`,
   `result.json`, `latent.npy`): that folder is the editable composition, so
   never delete it.
6. Gate: every requested take exists as a non-empty WAV with valid metadata.
   If a result reports `"truncated": true`, the audio is still usable — report
   it as a caveat (usually lyrics too long for the model's token budget).
7. **Report quick facts, then offer next actions.** Present a compact table
   per take: model, audio duration, generation wall time (elapsed_s), RTF, MP3
   size (and the player link when the artifact server runs). Then ask the user
   to choose one:
   - **Generate 3 more takes**
   - **Generate 1 more take**
   - **Run auto-judgement** (metrics + CLAP ranking)
   - **Done / edit caption & lyrics**

   Loop back to step 2 for generation choices (seeds continue cycling);
   invoke `judge-quality` only after an explicit yes to that option.

## Learnings protocol

When the user corrects a mistake, or a take/session goes wrong in a way the
skill did not anticipate: append a dated entry to
`studio/learnings/LEARNINGS.md` (Symptom / Cause / Rule) in the same turn —
do not defer it. Create the folder/file if missing. Rules there override habit
on every future session.

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

- **`minimax-music3` takes:** wall time scales with the length budget (25 frames
  = 1 second; `--max-new-tokens` on local, `--duration-sec` on audiocpp). When
  iterating a prompt with the user, render **short clips first**
  (`--max-new-tokens 300–750` ≈ `--duration-sec 12–30`) and only render full
  length once the style is approved.
- **`yue2` takes:** upstream exposes **no length control at all** — length is
  emergent from the model, so `--duration-sec` is rejected and there is no
  clip-first shortcut. That is acceptable because a full ~3.6-minute song costs
  only ~70 s on a 4090. Iterate on `style.txt`, not on length; if you truly need
  a shorter render, that is a `minimax-music3` job.

## Failure handling

| Symptom | Action |
|---|---|
| Server unhealthy mid-batch (`minimax-music3`/local) | Stop remaining takes; `serve.py status`; restart if needed; rerun only missing takes |
| Generation exceeds health timeout | Kill job, mark take failed in metadata, retry once |
| Content filter rejection | Report to user with reason; adjust brief/caption via compose-brief |
| Truncated/silent audio | Keep the file, flag it; judge-quality will quantify the defect. `"truncated": true` on a yue2 take means the model hit its token budget — usually lyrics that are too long; shorten them via compose-brief |
| `yue2` reports it is not installed | `python scripts/setup_yue2.py` (one-time, ~8 GB of weights) — do not hand-install inside WSL |
| `yue2` reports no CUDA inside the runtime | Reinstall the NVIDIA Windows driver, `wsl.exe --shutdown`, retest; report rather than editing the WSL install by hand |
| `yue2` reports *lyrics.txt is empty* | YuE2 has no instrumental mode — and neither does MiniMax Music 3. Do not switch models hoping to unlock it and do not stub placeholder lyrics to get past the guard: tell the user instrumental-only is unsupported (`plans/2026-09-14-instrumental-generation-unsupported.md`) and let them decide |
| `warnings` in the result mentions *empty lyrics* | The take was an instrumental attempt. It will very likely contain vocals: report that plainly instead of presenting it as the instrumental the user asked for, and offer to re-render as a vocal song |
| Job id `unknown` / GPU idle after dispatch | Dispatch was silently lost: relaunch as a fresh background job and verify GPU utilization before reporting any ETA |

Never delete failed takes — rename with `_failed` suffix so evidence persists.
That includes a failed yue2 attempt: its `takes/take-NN.yue2/` folder is moved to
`take-NN.yue2_failed` automatically by the generator, and a retry then starts
from a clean directory.

## Handoff

Generation is iterative: after each batch, the user may request more takes
(1 or 3), run `judge-quality` (only on explicit confirmation), edit caption &
lyrics via `compose-brief`, or declare done. When judging is chosen, invoke
`judge-quality` on the session folder and present the ranked results table;
otherwise close the batch with player/download links and await the next choice.
