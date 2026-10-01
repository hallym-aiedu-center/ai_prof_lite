FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV CONDA_DIR=/opt/conda

# ------------------------------------------------------------
# System packages
# ------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    build-essential \
    ca-certificates \
    curl \
    ffmpeg \
    fonts-noto-cjk \
    git \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    libsm6 \
    libxext6 \
    libxrender1 \
    tini \
    zlib1g \
    && rm -rf /var/lib/apt/lists/*

# ------------------------------------------------------------
# Miniconda
#
# Base environment is used only to manage Conda.
# The application itself runs in a single "runtime" environment.
# ------------------------------------------------------------
ARG MINICONDA_VERSION=py310_26.7.1-1
ARG MINICONDA_SHA256=fb1af4c45e6e73fe193c2398b4346b1e45522f729cdfccfdb18f6c765954dbd9

RUN curl -fsSL \
      -o /tmp/miniconda.sh \
      "https://repo.anaconda.com/miniconda/Miniconda3-${MINICONDA_VERSION}-Linux-x86_64.sh" \
    && echo "${MINICONDA_SHA256}  /tmp/miniconda.sh" | sha256sum -c - \
    && bash /tmp/miniconda.sh -b -p ${CONDA_DIR} \
    && rm -f /tmp/miniconda.sh \
    && ${CONDA_DIR}/bin/conda config --system --set auto_update_conda false \
    && (${CONDA_DIR}/bin/conda tos accept \
          --override-channels \
          --channel https://repo.anaconda.com/pkgs/main || true) \
    && (${CONDA_DIR}/bin/conda tos accept \
          --override-channels \
          --channel https://repo.anaconda.com/pkgs/r || true)

# ------------------------------------------------------------
# Single Python 3.10 runtime environment
# ------------------------------------------------------------
RUN ${CONDA_DIR}/bin/conda create -y \
      -n runtime \
      python=3.10 \
      pip

ENV PATH=${CONDA_DIR}/envs/runtime/bin:${CONDA_DIR}/bin:${PATH}

WORKDIR /app

# ------------------------------------------------------------
# Application dependencies
# ------------------------------------------------------------
COPY requirements.txt /tmp/requirements.txt

RUN python --version \
    && which python \
    && python -m pip install --upgrade \
         pip \
         setuptools \
         wheel \
         packaging \
    && python -m pip install \
         -r /tmp/requirements.txt

# ------------------------------------------------------------
# PyTorch CUDA 12.1
# ------------------------------------------------------------
RUN python -m pip install \
    torch==2.3.1 \
    torchvision==0.18.1 \
    torchaudio==2.3.1 \
    --index-url https://download.pytorch.org/whl/cu121

# ------------------------------------------------------------
# Ditto dependencies
#
# Application and Ditto share this same Python environment.
#
# Packages already managed by requirements.txt such as:
#   cffi
#   Pillow
#   pycparser
#   rembg
# are not downgraded here.
# ------------------------------------------------------------
RUN python -m pip install \
    numpy==2.0.1 \
    audioread==3.0.1 \
    cuda-python==12.1.0 \
    cython==3.0.11 \
    decorator==5.1.1 \
    einops==0.8.1 \
    filetype==1.2.0 \
    imageio==2.36.1 \
    imageio-ffmpeg==0.5.1 \
    joblib==1.4.2 \
    lazy-loader==0.4 \
    librosa==0.10.2.post1 \
    llvmlite==0.43.0 \
    msgpack==1.1.0 \
    numba==0.60.0 \
    opencv-python-headless==4.10.0.84 \
    platformdirs==4.3.6 \
    pooch==1.8.2 \
    pyyaml==6.0.2 \
    requests==2.32.3 \
    scikit-image==0.25.0 \
    scikit-learn==1.6.0 \
    scipy==1.15.0 \
    soundfile==0.13.0 \
    soxr==0.5.0.post1 \
    threadpoolctl==3.5.0 \
    tifffile==2024.12.12 \
    tqdm==4.67.1

# ------------------------------------------------------------
# TensorRT 8.6.1
# ------------------------------------------------------------
RUN python -m pip install \
    tensorrt-bindings==8.6.1 \
    tensorrt-libs==8.6.1 \
    --extra-index-url https://pypi.nvidia.com

RUN python -m pip install \
    --no-build-isolation \
    --no-deps \
    tensorrt==8.6.1 \
    --extra-index-url https://pypi.nvidia.com

RUN python -m pip install \
    polygraphy \
    colored

# ------------------------------------------------------------
# Verify dependency consistency
# ------------------------------------------------------------
RUN python -m pip check

# ------------------------------------------------------------
# Verify unified Python / CUDA / cuDNN / TensorRT
# ------------------------------------------------------------
RUN python - <<'PY'
import sys

import aiosqlite
import fastapi
import numpy as np
import torch
import tensorrt as trt

print("================================")
print("Python    :", sys.version.split()[0])
print("Executable:", sys.executable)
print("FastAPI   :", fastapi.__version__)
print("NumPy     :", np.__version__)
print("PyTorch   :", torch.__version__)
print("CUDA      :", torch.version.cuda)
print("cuDNN     :", torch.backends.cudnn.version())
print("TensorRT  :", trt.__version__)
print("================================")

assert sys.version_info[:2] == (3, 10), sys.version
assert sys.executable == "/opt/conda/envs/runtime/bin/python", sys.executable

assert np.__version__ == "2.0.1", np.__version__
assert hasattr(np, "atan2")

assert torch.version.cuda is not None
assert torch.version.cuda.startswith("12.1"), torch.version.cuda

cudnn = torch.backends.cudnn.version()
assert cudnn is not None
assert str(cudnn).startswith("8"), cudnn

assert trt.__version__.startswith("8.6.1"), trt.__version__
PY

# ------------------------------------------------------------
# Cleanup build caches
# ------------------------------------------------------------
RUN ${CONDA_DIR}/bin/conda clean -afy \
    && rm -rf /root/.cache/pip \
    && rm -f /tmp/requirements.txt

# ------------------------------------------------------------
# Non-root runtime user
#
# Fixed UID/GID makes bind-mounted volume permissions predictable
# on Linux hosts.
# ------------------------------------------------------------
ARG APP_UID=10001
ARG APP_GID=10001

RUN groupadd \
      --gid ${APP_GID} \
      app \
    && useradd \
      --uid ${APP_UID} \
      --gid ${APP_GID} \
      --create-home \
      --home-dir /home/app \
      --shell /usr/sbin/nologin \
      app

# ------------------------------------------------------------
# Application source
# ------------------------------------------------------------
COPY --chown=app:app . /app

# ------------------------------------------------------------
# Writable runtime directories
#
# Keep application source non-root while explicitly preparing
# directories that the application is expected to write to.
# ------------------------------------------------------------
RUN mkdir -p \
      /app/data \
      /home/app/.cache \
    && chown -R app:app \
      /app/data \
      /home/app

# ------------------------------------------------------------
# Runtime environment
# ------------------------------------------------------------
ENV HOME=/home/app
ENV XDG_CACHE_HOME=/home/app/.cache

ENV APP_HOST=0.0.0.0
ENV APP_PORT=8002
ENV APP_RELOAD=0

ENV DATA_DIR=/app/data

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# ------------------------------------------------------------
# Drop root privileges
#
# Everything below this point, including tini and Python,
# runs as the unprivileged application user.
# ------------------------------------------------------------
USER app:app

EXPOSE 8002

ENTRYPOINT ["/usr/bin/tini", "--"]

CMD ["/opt/conda/envs/runtime/bin/python", "app.py"]