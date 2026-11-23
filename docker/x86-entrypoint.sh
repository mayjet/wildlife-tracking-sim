#!/usr/bin/env bash
set -euo pipefail

GUI_ENABLED="${GUI_ENABLED:-0}"
DISPLAY_NUMBER="${DISPLAY_NUMBER:-1}"
NOVNC_PORT="${NOVNC_PORT:-6080}"
VNC_PORT="${VNC_PORT:-5900}"

if [[ "${GUI_ENABLED}" == "1" ]]; then
  if [[ "${GUI_AVAILABLE:-0}" != "1" ]]; then
    echo "GUI_ENABLED=1 was requested, but this image was built with INSTALL_GUI=0" >&2
    exit 2
  fi
  if [[ -z "${VNC_PASSWORD:-}" ]]; then
    echo "VNC_PASSWORD is required when GUI_ENABLED=1" >&2
    exit 2
  fi

  export DISPLAY=":${DISPLAY_NUMBER}"
  runtime_directory="${XDG_RUNTIME_DIR:-/tmp/wildlife-runtime}"
  home_directory="${HOME:-/tmp/wildlife-home}"
  password_file="${runtime_directory}/vnc.pass"
  mkdir -p "${runtime_directory}" "${home_directory}"
  chmod 700 "${runtime_directory}"

  Xvfb "${DISPLAY}" -screen 0 "${GUI_SCREEN:-1920x1080x24}" -nolisten tcp &
  xvfb_pid=$!
  for _ in $(seq 1 50); do
    [[ -S "/tmp/.X11-unix/X${DISPLAY_NUMBER}" ]] && break
    sleep 0.1
  done
  if [[ ! -S "/tmp/.X11-unix/X${DISPLAY_NUMBER}" ]]; then
    echo "virtual X display did not start" >&2
    exit 3
  fi

  openbox-session >"${runtime_directory}/openbox.log" 2>&1 &
  x11vnc -storepasswd "${VNC_PASSWORD}" "${password_file}" >/dev/null
  x11vnc \
    -display "${DISPLAY}" \
    -rfbport "${VNC_PORT}" \
    -rfbauth "${password_file}" \
    -forever \
    -shared \
    -localhost \
    >"${runtime_directory}/x11vnc.log" 2>&1 &
  websockify --web /usr/share/novnc/ "${NOVNC_PORT}" "127.0.0.1:${VNC_PORT}" \
    >"${runtime_directory}/novnc.log" 2>&1 &

  cleanup() {
    kill "${xvfb_pid}" 2>/dev/null || true
  }
  trap cleanup EXIT INT TERM
  echo "Genesis desktop: http://127.0.0.1:${NOVNC_PORT}/vnc.html"
fi

exec "$@"
