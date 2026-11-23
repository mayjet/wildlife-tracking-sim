FROM ghcr.io/astral-sh/uv:0.11.12 AS uv
FROM nvidia/cuda:12.8.1-runtime-ubuntu22.04

ARG INSTALL_GUI=1

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:/usr/local/bin:/usr/bin:/bin \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility,graphics,display \
    PYTHONPATH=/workspace/libs/shepherd-contracts/src:/workspace/packages/field-environment/src:/workspace/packages/field-campost/src:/workspace/packages/field-sim/src:/workspace/packages/field-tracker/src:/workspace/packages/field-benchmark/src:/workspace/packages/field-visualizer/src

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        git \
        libegl1 \
        libgl1 \
        libglu1-mesa \
        libglib2.0-0 \
        libgomp1 \
        libsm6 \
        libvulkan1 \
        libx11-6 \
        libxcursor1 \
        libxext6 \
        libxfixes3 \
        libxi6 \
        libxinerama1 \
        libxrandr2 \
        libxrender1 \
        libxxf86vm1 \
        python3 \
        python3-venv \
        tini \
    && if [ "${INSTALL_GUI}" = "1" ]; then \
        apt-get install -y --no-install-recommends \
          dbus-x11 \
          fonts-dejavu-core \
          mesa-utils \
          novnc \
          openbox \
          websockify \
          x11vnc \
          xterm \
          xvfb; \
    fi \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /uvx /usr/local/bin/
WORKDIR /workspace
COPY . /workspace
RUN uv sync --locked --extra x86 --no-editable

RUN python3 -c "import embreex, genesis, rerun, torch; assert torch.version.cuda is not None"

COPY docker/x86-entrypoint.sh /usr/local/bin/wildlife-x86-entrypoint
RUN chmod 0755 /usr/local/bin/wildlife-x86-entrypoint

ENV GUI_AVAILABLE=${INSTALL_GUI}
EXPOSE 6080 9090 9876
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/wildlife-x86-entrypoint"]
CMD ["sleep", "infinity"]
