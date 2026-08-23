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

1. `sessions/<song-id>/caption.md` and `lyrics.txt` exist.
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
   python scripts/generate_audiocpp.py --session sessions/<song-id> --seed <seed>

   # type = "local"
   python scripts/generate.py --session sessions/<song-id> --seed <seed>
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

Never delete failed takes — rename with `_failed` suffix so evidence persists.

## Handoff

On completion, invoke `judge-quality` on the session folder, then present the
ranked results table to the user.
