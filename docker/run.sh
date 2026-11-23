#!/usr/bin/env bash
set -euo pipefail

# GUIあり（標準）:
#   VNC_PASSWORD='change-me' INSTALL_GUI=1 GUI_ENABLED=1 docker/run.sh
# GUIなし（buildもruntimeも最小化）:
#   # INSTALL_GUI=0 GUI_ENABLED=0 docker/run.sh

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

INSTALL_GUI="${INSTALL_GUI:-1}"
GUI_ENABLED="${GUI_ENABLED:-${INSTALL_GUI}}"
WEB_BIND_ADDRESS="${WEB_BIND_ADDRESS:-127.0.0.1}"
NOVNC_PORT="${NOVNC_PORT:-6080}"
RERUN_WEB_PORT="${RERUN_WEB_PORT:-9090}"
RERUN_GRPC_PORT="${RERUN_GRPC_PORT:-9876}"

if [[ "${INSTALL_GUI}" != "0" && "${INSTALL_GUI}" != "1" ]]; then
  echo "INSTALL_GUI must be 0 or 1" >&2
  exit 2
fi
if [[ "${GUI_ENABLED}" != "0" && "${GUI_ENABLED}" != "1" ]]; then
  echo "GUI_ENABLED must be 0 or 1" >&2
  exit 2
fi
if [[ "${GUI_ENABLED}" == "1" && -z "${VNC_PASSWORD:-}" ]]; then
  echo "VNC_PASSWORD is required when GUI_ENABLED=1" >&2
  exit 2
fi

docker build \
  --file "${SCRIPT_DIR}/Dockerfile" \
  --build-arg "INSTALL_GUI=${INSTALL_GUI}" \
  --tag wildlife-tracking-sim:x86 \
  "${REPOSITORY_ROOT}"

run_arguments=(
  --detach
  --name wildlife-tracking-sim-x86
  --gpus all
  --network bridge
  --shm-size 4g
  --user "$(id -u):$(id -g)"
  --env "GUI_ENABLED=${GUI_ENABLED}"
  --env "HOME=/tmp/wildlife-home"
  --env "XDG_RUNTIME_DIR=/tmp/wildlife-runtime"
  --env "NVIDIA_DRIVER_CAPABILITIES=compute,utility,graphics,display"
  --workdir /workspace
  --mount "type=bind,source=${REPOSITORY_ROOT},target=/workspace"
  --publish "${WEB_BIND_ADDRESS}:${RERUN_WEB_PORT}:9090"
  --publish "${WEB_BIND_ADDRESS}:${RERUN_GRPC_PORT}:9876"
)

if [[ "${GUI_ENABLED}" == "1" ]]; then
  run_arguments+=(
    --env "VNC_PASSWORD=${VNC_PASSWORD}"
    --publish "${WEB_BIND_ADDRESS}:${NOVNC_PORT}:6080"
  )
fi

docker run "${run_arguments[@]}" wildlife-tracking-sim:x86

echo "Container: wildlife-tracking-sim-x86"
echo "Rerun Web: http://${WEB_BIND_ADDRESS}:${RERUN_WEB_PORT}"
if [[ "${GUI_ENABLED}" == "1" ]]; then
  echo "Genesis noVNC: http://${WEB_BIND_ADDRESS}:${NOVNC_PORT}/vnc.html"
fi
