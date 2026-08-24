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

1. Read take count + seeds from `configs/provider.toml` (`[generation]`,
   default 3 takes, seeds cycled).
2. **Dispatch takes SEQUENTIALLY** — measured faster than concurrent dispatch
   on single-GPU hosts (see plans/2026-08-23-performance-research.md).
3. For each take, run as a **background job**:

   ```bash
   # type = "audiocpp" (default)
   python scripts/generate_audiocpp.py --session studio/sessions/<song-id> --seed <seed>

   # type = "local"
   python scripts/generate.py --session studio/sessions/<song-id> --seed <seed>
   ```

4. Parse each result's `generate/v1` JSON. On success it names the written
   WAV and its sidecar `metadata.json`. audiocpp results carry additive
   fields (`provider`, `rtf`, and `mp3`/`mp3_bytes` when the MP3 companion
   is enabled — it is by default).
5. Gate: every requested take exists as a non-empty WAV with valid metadata;
   report duration from metadata.
6. For browser access from other devices, mention the artifact server:
   `python scripts/serve_artifacts.py` behind Tailscale Serve serves every
   session's takes with play/download links — see
   plans/2026-08-23-harness-web-integration.md.

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

On completion, invoke `judge-quality` on the session folder, then present the
ranked results table to the user.
