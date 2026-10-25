FROM nvidia/cuda:12.6.3-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/workspace/libs/shepherd-contracts/src:/workspace/packages/field-environment/src:/workspace/packages/field-campost/src:/workspace/packages/field-sim/src

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        git \
        libgl1 \
        libglib2.0-0 \
        python3 \
        python3-pip \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN python3 -m pip install --upgrade pip \
    && python3 -m pip install -r /tmp/requirements.txt

COPY libs/shepherd-contracts /tmp/shepherd-contracts
COPY packages/field-environment /tmp/field-environment
COPY packages/field-campost /tmp/field-campost
COPY packages/field-sim /tmp/field-sim
RUN python3 -m pip install /tmp/shepherd-contracts /tmp/field-environment /tmp/field-campost /tmp/field-sim \
    && rm -rf /tmp/shepherd-contracts /tmp/field-environment /tmp/field-campost /tmp/field-sim

WORKDIR /workspace
CMD ["sleep", "infinity"]
