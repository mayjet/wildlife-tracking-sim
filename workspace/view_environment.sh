#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="${CONTAINER_NAME:-wildlife-miyota-dev}"
CASE_ID="${CASE_ID:-MiyotaMtBase_gsi_3km_v1}"
GENESIS_DISPLAY="${GENESIS_DISPLAY:-:1}"
BACKEND="${BACKEND:-cpu}"
FOCUS="${FOCUS:-terrain}"

DISPLAY_NUMBER="${GENESIS_DISPLAY#:}"
DISPLAY_NUMBER="${DISPLAY_NUMBER%%.*}"
X11_SOCKET="/tmp/.X11-unix/X${DISPLAY_NUMBER}"

if [[ ! -S "${X11_SOCKET}" ]]; then
    echo "X11 socket not found: ${X11_SOCKET}" >&2
    ls -l /tmp/.X11-unix/ >&2
    exit 1
fi

if [[ "$(docker inspect --format '{{.State.Running}}' "${CONTAINER_NAME}" 2>/dev/null)" != "true" ]]; then
    echo "Docker container is not running: ${CONTAINER_NAME}" >&2
    exit 1
fi

cleanup() {
    DISPLAY="${GENESIS_DISPLAY}" xhost -si:localuser:root >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

DISPLAY="${GENESIS_DISPLAY}" xhost +si:localuser:root
docker exec -it \
    -e DISPLAY="${GENESIS_DISPLAY}" \
    "${CONTAINER_NAME}" \
    python3 workspace/view_environment.py \
        --case-id "${CASE_ID}" \
        --backend "${BACKEND}" \
        --focus "${FOCUS}"
