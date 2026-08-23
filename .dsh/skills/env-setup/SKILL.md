---
name: env-setup
description: >
  One-time machine bring-up for agentic-music. Two provider paths:
  (A, default) audio.cpp GGUF CLI — Windows-native, no WSL needed for
  generation; (B) SGLang-Omni reference stack in WSL2. Use when the pipeline
  reports a missing tool/weights/server, or on any fresh machine.
---

# Skill: env-setup

Bring a machine from zero to generating music locally with MiniMax Music 3.
Execute steps **in order**; every step gates the next. Never skip a failed gate.

## Path selection

Read `[provider].type` from `configs/provider.toml`:

- **`"audiocpp"` (default)** — do Steps 1 → 4a. Steps 2–5 and 6 are only
  required if you also want the SGLang-Omni reference stack (path B).
- **`"local"`** — do all steps.

## Step 1 — Hardware audit

```bash
python scripts/hardware_audit.py
```

Parse `hardware_audit/v1`. Gate: `verdict.single_gpu_vram_ok == true`.
If false, STOP and report — decision D1 (single RTX 4090 class GPU) is not met.
Note `disks[]` free space: ≥60 GB must be free where WSL stores its disk
(usually C:) before downloading ~25 GB of weights.

## Step 2 — Linux side preparation (Windows host only; path B)

The SGLang-Omni reference stack runs inside WSL2 distro `Ubuntu-24.04`.
Skip this step when only the default audiocpp provider is needed.

```powershell
wsl.exe --list --quiet          # does it exist?
# if missing:
wsl.exe --install -d Ubuntu-24.04 --no-launch --web-download
```

Smoke test after install:

```bash
wsl.exe -d Ubuntu-24.04 -u root -- bash -c "nvidia-smi --query-gpu=name,memory.total --format=csv,noheader && curl -sI https://huggingface.co -o /dev/null -w '%{http_code}\n'"
```

Gate: GPU line visible AND HTTP 200. Repo path inside WSL is
`/mnt/<drive>/…` of this repository's Windows location.

## Step 3 — Pin and verify upstream references

```bash
wsl.exe -d Ubuntu-24.04 -u root -- bash <repo-in-wsl>/scripts/fetch_upstream.sh
```

Parse `fetch_upstream/v1`. Gate: `"ok": true`, both repos verified, zero
`missing_required_files`. This also regenerates `docs/upstream.md`.

## Step 4 — Isolated environment + server stack

```bash
wsl.exe -d Ubuntu-24.04 -u root -- bash <repo-in-wsl>/scripts/env_setup.sh --with-server
```

Long-running (torch + sglang-omni): run as a background job. Parse
`env_setup/v1`. Gate: `"ok": true`, `steps[].status != "failed"` for
`uv-install`, `venv-create`, `base-deps`, `system-deps`, `server-deps`,
and `server_stack.installed == true`.
If `server-deps` failed: read stderr of the job; typical causes are missing
build tools (script now installs them) or resolver conflicts — fix the script,
do not work around by hand.

## Step 4a — audio.cpp GGUF provider setup (default path A ends here)

Windows-native, no WSL. Run as a background job (≈19 GB of downloads on a
fresh machine: 246 MB CLI + 549 MB CUDA runtime + ~19 GB GGUF components):

```bash
python scripts/setup_audiocpp.py
```

Parse `setup_audiocpp/v1`. Gate: `"ok": true` and
`.tools/audiocpp/audiocpp_cli.exe` exists. The script is idempotent — it
skips anything already present, and assembles the all-Q8 hardlink model dir.
Smoke test generation:

```bash
python scripts/generate_audiocpp.py --session studio/sessions/<any-session> \
  --seed 7 --duration-sec 10 --take-id 900
```

Gate: `generate/v1` with `"ok": true` and a non-empty WAV.

## Step 5 — Model weights download (path B)

Resumable; safe to re-run. Run inside WSL as a background job:

```bash
/root/agentic-music-venv/bin/hf download MiniMaxAI/MiniMax-Music3 \
  --local-dir ~/models/minimax-music3
```

(Use the `hf` binary — `huggingface-cli` is removed in current huggingface_hub.)

Gate: command exits 0 and `~/models/minimax-music3` contains the expected
weight files (`*.safetensors` present, no `.incomplete`/lock files).
Expect roughly 20–30 GB. Record elapsed time and final byte count.

## Step 6 — Serve + healthcheck (path B)

The WSL Ubuntu image runs systemd: session-scoped daemons get SIGKILLed when
the launching console disconnects. Therefore run the server **in the
foreground of a persistent background job** (harness job / tmux pane):

```bash
python scripts/serve.py run       # foreground; keep the wrapping job alive
python scripts/serve.py status    # until "healthy": true (poll, do not busy-wait)
```

First startup loads tens of GB of weights; allow up to `health_timeout_s`
(configs/provider.toml). Gate: `/v1/models` or `/health` responds and VRAM
usage is logged. **Record peak VRAM during a short generation — this is the
Phase 0 go/no-go evidence** (plans/2026-08-23-phase0-single-gpu-spike.md).

Single-GPU note: colocated serving requires an exported pipeline config —
`sgl-omni config export --model-path <weights> --output-path <cfg>` — already
wired through `configs/provider.toml` (`pipeline_config_wsl` +
`extra_serve_args`).

## Failure handling

| Symptom | Action |
|---|---|
| nvidia-smi missing inside WSL | Reinstall NVIDIA Windows driver (WSL CUDA passthrough ships with it), reboot, retest |
| apt/uv network errors | Check DNS/proxy; retry once; report if persistent |
| Weight download interrupted | Just rerun Step 5 — it resumes |
| Server OOM at startup | STOP. Single-GPU hypothesis failed; record measurements in a new dated plan document before proposing mitigations |
