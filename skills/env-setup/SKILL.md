---
name: env-setup
description: >
  One-time machine bring-up for agentic-music: hardware audit, WSL2/Ubuntu
  preparation, isolated uv environment, pinned upstream fetch, model weight
  download, local SGLang-Omni server launch, and healthcheck. Use when the
  pipeline reports no healthy server, or on any fresh machine.
---

# Skill: env-setup

Bring a machine from zero to a healthy, locally served MiniMax Music 3 endpoint.
Execute steps **in order**; every step gates the next. Never skip a failed gate.

## Step 1 — Hardware audit

```bash
python scripts/hardware_audit.py
```

Parse `hardware_audit/v1`. Gate: `verdict.single_gpu_vram_ok == true`.
If false, STOP and report — decision D1 (single RTX 4090 class GPU) is not met.
Note `disks[]` free space: ≥60 GB must be free where WSL stores its disk
(usually C:) before downloading ~25 GB of weights.

## Step 2 — Linux side preparation (Windows host only)

The inference stack runs inside WSL2 distro `Ubuntu-24.04`.

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

## Step 5 — Model weights download

Resumable; safe to re-run. Run inside WSL as a background job:

```bash
/root/agentic-music-venv/bin/hf download MiniMaxAI/MiniMax-Music3 \
  --local-dir ~/models/minimax-music3
```

(Use the `hf` binary — `huggingface-cli` is removed in current huggingface_hub.)

Gate: command exits 0 and `~/models/minimax-music3` contains the expected
weight files (`*.safetensors` present, no `.incomplete`/lock files).
Expect roughly 20–30 GB. Record elapsed time and final byte count.

## Step 6 — Serve + healthcheck

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
