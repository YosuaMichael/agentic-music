---
name: env-setup
description: >
  One-time machine bring-up for agentic-music. Three runtimes: (A) audio.cpp
  GGUF CLI for MiniMax Music 3 — Windows-native; (B) SGLang-Omni reference
  stack in WSL2 for MiniMax Music 3; (C) YuE2 — the DEFAULT music model —
  which is Linux-only upstream and therefore runs in WSL2 on Windows. Use when
  the pipeline reports a missing tool/weights/runtime, or on a fresh machine.
---

# Skill: env-setup

Bring a machine from zero to generating music locally. Execute steps **in
order**; every step gates the next. Never skip a failed gate.

## Path selection

The music model is chosen per session (default `yue2`); a machine may install
one or both runtimes. Start from what a session will actually need:

| Model chosen in the session | Set up |
|---|---|
| **`yue2` (default)** | Step 1 → Step 2 (WSL only, if on Windows) → Step 3 → **Step 4b** |
| `minimax-music3`, engine `audiocpp` | Step 1 → Step 3 → Step 4a (no WSL needed) |
| `minimax-music3`, engine `local` | all steps |

Read the defaults from `configs/provider.toml`: `[models].default` is the
model a fresh machine should be able to run first, and `[provider].type`
(`"audiocpp"` | `"local"`) selects the MiniMax Music 3 engine.

Installing everything is fine and they coexist: YuE2 needs ~8 GB of weights and
its own WSL venv, MiniMax Music 3 Q8 needs ~19 GB under `models/audiocpp/`.
They cannot generate simultaneously on one GPU (YuE2 is one request at a time
and peaks ~14 GiB; the SGLang path takes ~24 GB) — but that is a runtime
concern, not an install conflict.

## Step 1 — Hardware audit

```bash
python scripts/hardware_audit.py
```

Parse `hardware_audit/v1`. Gate: `verdict.single_gpu_vram_ok == true`.
If false, STOP and report — decision D1 (single RTX 4090 class GPU) is not met.
Note `disks[]` free space: ≥60 GB must be free where WSL stores its disk
(usually C:) before downloading ~25 GB of weights (both runtimes combined:
~19 GB MiniMax GGUF + ~8 GB YuE2). YuE2 additionally documents **24 GB host
RAM** and Windows on a 24 GB card reports 24564 MiB, not 24576 — treat the bar
as "24 GB class", which `setup_yue2.py` already encodes.

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

Fetches gitignored upstream checkouts into `oss/` (~few MB, no GPU). Plain
`bash`+`git` — works on Windows via Git Bash **without WSL**:

```bash
bash scripts/fetch_upstream.sh
# alternative (WSL path B): wsl.exe -d Ubuntu-24.04 -u root -- bash <repo-in-wsl>/scripts/fetch_upstream.sh
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
python scripts/generate_take.py --session studio/sessions/<any-session> \
  --model minimax-music3 --seed 7 --duration-sec 10 --take-id 900
```

Gate: `generate/v1` with `"ok": true` and a non-empty WAV.

## Step 4b — YuE2 runtime setup (default music model; WSL on Windows)

YuE2 is Linux-only upstream (no Windows instructions, `torch==2.10.0` pinned),
so on Windows it runs inside the same WSL2 distro as path B — hence Step 2 must
have passed first. On a Linux host it installs natively.

One command does the whole thing idempotently — venv inside WSL, installation
from the pinned checkout, weights, then the `yue2 doctor` gate. Run it as a
background job (multi-GB `torch` download + ~8 GB of weights; ~7.8 GB for the
model and VAE):

```bash
python scripts/setup_yue2.py
```

Parse `setup_yue2/v1`:
- Gate: `"ok": true`, and `venv_dir` + every entry of `weights_present` present.
- Gate: `"ready_for_generation": true`. If `ok` is true but this is false, read
  `cuda_visible` and `doctor_ok` plus the `warnings[]` list — the runtime
  installed but cannot generate yet (usually GPU passthrough into WSL).
- `installed_version` should be `0.1.6` (upstream's current release).
- Re-run the script freely: it skips whatever already exists. `--force`
  reinstalls, `--skip-weights` installs the runtime only, and
  `--install-source wheel` uses the pinned v0.1.6 release archive instead of the
  checkout — only as a fallback, since that archive bundles first-party code
  under CC BY-NC 4.0 as well as the weights.

If Step 3 was skipped, this step will run `scripts/fetch_upstream.sh` itself to
get `oss/yue2` (the pinned checkout it installs from).

Smoke-test generation against any prepared session (no model can do
instrumentals, so the session needs non-empty lyrics and a `style.txt`):

```bash
python scripts/generate_take.py --session studio/sessions/<any-session> \
  --model yue2 --seed 831001 --take-id 900
```

Gate: `generate/v1` with `"ok": true`, a non-empty WAV, and a
`takes/take-900.yue2/` folder containing `score.abc`. Then confirm readiness
the way the studio will see it:

```bash
python scripts/select_model.py --list      # yue2 must report "ready": true
```

**Licence:** YuE2's first-party code is Apache-2.0, but its **weights are
CC BY-NC 4.0 — non-commercial only**. Say this when reporting setup to the user;
never imply YuE2 output is commercially usable.

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
| Weight download interrupted | Just rerun the step — `setup_yue2.py` and `hf download` both resume/skip |
| Server OOM at startup | STOP. Single-GPU hypothesis failed; record measurements in a new dated plan document before proposing mitigations |
| `setup_yue2.py` says the runtime is not usable, "Access is denied" | WSL itself refused the call — verify with `wsl.exe -d Ubuntu-24.04 -u root -- echo ok`. A missing distro is a Step 2 job; a permission error is an environment/host problem to report, not to work around |
| `setup_yue2.py` `ok: true` but `ready_for_generation: false` | Read `cuda_visible`/`doctor_ok` and `warnings[]`. `cuda_visible: false` = GPU passthrough: reinstall the NVIDIA driver, `wsl.exe --shutdown`, rerun |
| `setup_yue2.py` fails in `pip install` | Report `error` verbatim (it carries the pip tail). Do not hand-install into the WSL venv; the pinned checkout is the supported source. No `flash-attn`/Triton build is needed — a compile failure means something else changed |
| `python3.12` not found in the distro | Install it (`apt-get install -y python3.12 python3.12-venv`) or point `[yue2].python` at an interpreter ≥3.10 that exists |
| venv creation fails with "ensurepip is not available" | Ubuntu ships `venv` without pip: `apt-get update && apt-get install -y python3.12-venv` (encountered for real on 2026-09-13; `apt-get update` first or the install 404s) |
| Generation takes ~5 minutes for a 2-minute song | The model is revalidating weights online. Confirm `[yue2].offline = true`; measured 299.5 s online vs 54.7 s offline for the same take |
