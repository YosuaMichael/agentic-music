#!/usr/bin/env bash
# env_setup.sh — isolated Python environment setup INSIDE the Linux/WSL side.
#
# Creates/refreshes a uv-managed virtualenv at ~/agentic-music-venv, installs base
# pipeline dependencies, and optionally the inference server stack (--with-server),
# which is large (torch + SGLang-Omni, multi-GB) and therefore skippable.
#
# Usage: scripts/env_setup.sh [--with-server]
#
# JSON contract (stdout):
#
#   env_setup/v1
#   {
#     "schema": "env_setup/v1",
#     "venv_path": "/root/agentic-music-venv",
#     "python_version": "3.12.x",
#     "uv_version": "0.10.x",
#     "steps": [ {"step": "uv-install|venv-create|base-deps|server-deps",
#                 "status": "ok|skipped|failed", "detail": "..."} ],
#     "server_stack": {"installed": true|false|null, "source": "pypi|git|null"},
#     "gpu_visible": true,
#     "ok": true|false
#   }

set -uo pipefail

WITH_SERVER=0
[[ "${1:-}" == "--with-server" ]] && WITH_SERVER=1

VENV="$HOME/agentic-music-venv"
STEPS_CSV=""
OK=1

step() {
  # step <name> <status> <detail>   (detail must not contain double quotes)
  STEPS_CSV+="{\"step\": \"$1\", \"status\": \"$2\", \"detail\": \"$3\"},"
  [[ "$2" == "failed" ]] && OK=0
  return 0
}

# --- uv -----------------------------------------------------------------------
UV_BIN="$HOME/.local/bin/uv"
if command -v uv >/dev/null 2>&1; then
  UV_BIN="$(command -v uv)"
fi
if [[ ! -x "$UV_BIN" ]]; then
  echo "[env_setup] installing uv..." >&2
  if curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1; then
    UV_BIN="$HOME/.local/bin/uv"
  fi
fi

UV_VERSION=""
if [[ -x "$UV_BIN" ]]; then
  UV_VERSION="$("$UV_BIN" --version 2>/dev/null | head -1)"
  step "uv-install" "ok" "$UV_VERSION"
else
  step "uv-install" "failed" "uv unavailable after install attempt"
fi

PY_VERSION="unknown"
if [[ -x "$UV_BIN" ]]; then
  # --- system build tools (some sgl-omni deps compile C extensions) ------------
  if command -v gcc >/dev/null 2>&1; then
    step "system-deps" "ok" "gcc present"
  elif command -v apt-get >/dev/null 2>&1; then
    echo "[env_setup] installing build-essential + python3-dev via apt..." >&2
    if apt-get update -qq >/dev/null 2>&1 &&
       DEBIAN_FRONTEND=noninteractive apt-get install -y -qq build-essential python3-dev ninja-build >/dev/null 2>&1; then
      step "system-deps" "ok" "installed build-essential python3-dev ninja-build"
    else
      step "system-deps" "failed" "apt install failed"
    fi
  else
    step "system-deps" "failed" "no gcc and no apt-get"
  fi

  # --- venv -------------------------------------------------------------------
  if "$UV_BIN" venv --python 3.12 "$VENV" --allow-existing >/dev/null 2>&1; then
    PY_VERSION="$("$VENV/bin/python" --version 2>&1)"
    step "venv-create" "ok" "$VENV ($PY_VERSION)"
  else
    PY_VERSION="$(python3 --version 2>&1 || echo unknown)"
    step "venv-create" "failed" "could not create $VENV"
  fi

  # --- base deps --------------------------------------------------------------
  if "$UV_BIN" pip install --python "$VENV/bin/python" huggingface_hub httpx >/dev/null 2>&1; then
    step "base-deps" "ok" "huggingface_hub httpx"
  else
    step "base-deps" "failed" "pip install failed"
  fi
else
  step "venv-create" "skipped" "no uv"
  step "base-deps" "skipped" "no uv"
fi

# --- server stack (optional) --------------------------------------------------
SERVER_INSTALLED="null"
SERVER_SOURCE="null"
if [[ "$WITH_SERVER" == "1" ]]; then
  if [[ -x "$UV_BIN" ]]; then
    echo "[env_setup] installing server stack (large download, minutes)..." >&2
    if curl -sf https://pypi.org/pypi/sglang-omni/json >/dev/null 2>&1 &&
       "$UV_BIN" pip install --python "$VENV/bin/python" sglang-omni >/dev/null 2>&1; then
      SERVER_INSTALLED=true
      SERVER_SOURCE=pypi
      step "server-deps" "ok" "sglang-omni from pypi"
    elif "$UV_BIN" pip install --python "$VENV/bin/python" "sglang-omni @ git+https://github.com/sgl-project/sglang-omni.git" >/dev/null 2>&1; then
      SERVER_INSTALLED=true
      SERVER_SOURCE=git
      step "server-deps" "ok" "sglang-omni from git"
    else
      SERVER_INSTALLED=false
      step "server-deps" "failed" "pypi and git install attempts failed"
    fi
  else
    step "server-deps" "skipped" "no uv"
  fi
else
  step "server-deps" "skipped" "not requested"
fi

GPU_VISIBLE=false
command -v nvidia-smi >/dev/null 2>&1 && GPU_VISIBLE=true

# --- nvcc for flashinfer JIT ---------------------------------------------------
# flashinfer compiles attention kernels on first use; it needs nvcc and falls
# back to /usr/local/cuda. Install ONLY the minimal NVIDIA repo packages.
if command -v nvcc >/dev/null 2>&1 || [[ -x /usr/local/cuda/bin/nvcc ]]; then
  step "nvcc" "ok" "already present"
elif command -v apt-get >/dev/null 2>&1; then
  echo "[env_setup] installing minimal CUDA toolchain (nvcc + cudart-dev)..." >&2
  KEYRING=/tmp/cuda-keyring_1.1-1_all.deb
  if curl -fsSL https://developer.download.nvidia.com/compute/cuda/repos/wsl-ubuntu/x86_64/cuda-keyring_1.1-1_all.deb -o "$KEYRING" &&
     dpkg -i "$KEYRING" >/dev/null 2>&1 &&
     apt-get update -qq >/dev/null 2>&1 &&
     DEBIAN_FRONTEND=noninteractive apt-get install -y -qq -o Dpkg::Options::=--force-confnew \
       cuda-nvcc-13-1 cuda-cudart-dev-13-1 >/dev/null 2>&1 &&
     ln -sfn /usr/local/cuda-13.1 /usr/local/cuda; then
    step "nvcc" "ok" "installed cuda-nvcc-13-1 via NVIDIA repo"
  elif curl -fsSL https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/cuda-keyring_1.1-1_all.deb -o "$KEYRING" &&
     dpkg -i "$KEYRING" >/dev/null 2>&1 &&
     apt-get update -qq >/dev/null 2>&1 &&
     DEBIAN_FRONTEND=noninteractive apt-get install -y -qq -o Dpkg::Options::=--force-confnew \
       cuda-nvcc-13-1 cuda-cudart-dev-13-1 >/dev/null 2>&1 &&
     ln -sfn /usr/local/cuda-13.1 /usr/local/cuda; then
    step "nvcc" "ok" "installed cuda-nvcc-13-1 via ubuntu2404 repo"
  else
    step "nvcc" "failed" "could not provision nvcc"
  fi
else
  step "nvcc" "skipped" "no apt-get"
fi

JOINED_STEPS="${STEPS_CSV%,}"
OK_STR=false
[[ "$OK" == 1 ]] && OK_STR=true

cat <<EOF
{
  "schema": "env_setup/v1",
  "venv_path": "$VENV",
  "python_version": "$PY_VERSION",
  "uv_version": "$UV_VERSION",
  "steps": [$JOINED_STEPS],
  "server_stack": {"installed": $SERVER_INSTALLED, "source": "$SERVER_SOURCE"},
  "gpu_visible": $GPU_VISIBLE,
  "ok": $OK_STR
}
EOF
