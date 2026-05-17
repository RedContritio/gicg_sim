# gicg_mono container image — Python venv + Go c-shared lib (libgicg.so).
#
# Multi-stage:
#   1. go-builder: build libgicg.so from gicg_engine/capi (cgo)
#   2. runtime: Python + venv + libgicg.so installed to /usr/local/lib
#
# Source code is NOT copied into the image — bind-mount the repo at
# runtime: ``-v $(pwd):/app:rw``. This way host edits flow into the
# container without rebuilding the image.
#
# Rebuild when:
#   - Go engine code changes (libgicg.so out of date)
#   - Python deps change (requirements.txt edit)
#
# Build:
#   docker compose build
#
# Run (one-shot training):
#   docker compose run --rm train python -m tools.gen_bc_dataset_az configs/...
#
# Run (eval daemon):
#   docker compose up -d eval

ARG PYTHON_VERSION=3.13
ARG GO_VERSION=1.23

# ---------- Stage 1: build libgicg.so ----------
FROM golang:${GO_VERSION}-bookworm AS go-builder

WORKDIR /src
# Copy only what's needed to build the .so. gicg_engine/capi imports
# gicg_mcts (same module, sibling package), so both directories must be
# present. Keep the build cache stable by avoiding broader copies.
COPY go.mod go.sum* ./
COPY gicg_engine/ ./gicg_engine/
COPY gicg_mcts/ ./gicg_mcts/

# CGO is required for buildmode=c-shared.
ENV CGO_ENABLED=1
RUN go mod download && \
    mkdir -p /out && \
    go build -buildmode=c-shared -o /out/libgicg.so ./gicg_engine/capi/ && \
    ls -la /out/libgicg.so

# ---------- Stage 2: Python runtime ----------
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app \
    LD_LIBRARY_PATH=/usr/local/lib

# System deps:
#   - libgomp1: OpenMP runtime needed by torch CPU
#   - ca-certificates: TLS for any HTTPS pip / runtime fetches
#   - tini: PID 1 init for clean signal handling on docker stop
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
        ca-certificates \
        tini && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps installed system-wide (no venv inside container — slim image
# already isolates).
#
# Use the CPU-only torch index. Default torch wheel pulls ~5GB of CUDA
# libs (cudnn / cusparselt / nccl / triton) even on CPU-only machines;
# the CPU index is ~250MB and matches what we actually run on macOS
# Docker Desktop (no GPU passthrough).
COPY requirements.txt ./
RUN pip install --upgrade pip && \
    pip install --index-url https://download.pytorch.org/whl/cpu torch && \
    pip install -r requirements.txt && \
    pip install tomli  # py<3.11 fallback; harmless on 3.13

# Bring in the compiled .so from go-builder.
COPY --from=go-builder /out/libgicg.so /usr/local/lib/libgicg.so

# Bind mount target — repo lands here at runtime.
# Image deliberately does NOT copy source; this keeps it small and lets
# host edits flow in without rebuild.
VOLUME ["/app"]

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-c", "print('container ready; specify command')"]
