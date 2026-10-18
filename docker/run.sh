#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

docker build \
  --file "${SCRIPT_DIR}/Dockerfile" \
  --tag wildlife-tracking-sim:x86 \
  "${REPOSITORY_ROOT}"

docker run \
  --detach \
  --name wildlife-tracking-sim-x86 \
  --gpus all \
  --network bridge \
  --user "$(id -u):$(id -g)" \
  --env HOME=/tmp \
  --workdir /workspace \
  --mount "type=bind,source=${REPOSITORY_ROOT},target=/workspace" \
  wildlife-tracking-sim:x86

