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
# ------------------------------------------------------------
RUN curl -fsSL -o /tmp/miniconda.sh \
      https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh \
    && bash /tmp/miniconda.sh -b -p ${CONDA_DIR} \
    && rm -f /tmp/miniconda.sh \
    && ${CONDA_DIR}/bin/conda config --system --set auto_update_conda false \
    && (${CONDA_DIR}/bin/conda tos accept \
          --override-channels \
          --channel https://repo.anaconda.com/pkgs/main || true) \
    && (${CONDA_DIR}/bin/conda tos accept \
          --override-channels \
          --channel https://repo.anaconda.com/pkgs/r || true)

ENV PATH=${CONDA_DIR}/bin:${PATH}

WORKDIR /app

# ------------------------------------------------------------
# Main application environment - Python 3.12
# ------------------------------------------------------------
COPY requirements.txt /tmp/requirements.txt

RUN conda create -y -n app python=3.12 pip \
    && ${CONDA_DIR}/envs/app/bin/python -m pip install \
         --upgrade pip setuptools wheel \
    && ${CONDA_DIR}/envs/app/bin/python -m pip install \
         -r /tmp/requirements.txt

# ------------------------------------------------------------
# Ditto environment - Python 3.10
# ------------------------------------------------------------
RUN conda create -y -n ditto python=3.10 pip \
    && ${CONDA_DIR}/envs/ditto/bin/python -m pip install \
         --upgrade pip setuptools wheel packaging

# ------------------------------------------------------------
# PyTorch CUDA 12.1
# This brings cuDNN 8.9.x
# ------------------------------------------------------------
RUN ${CONDA_DIR}/envs/ditto/bin/python -m pip install \
    torch==2.3.1 \
    torchvision==0.18.1 \
    torchaudio==2.3.1 \
    --index-url https://download.pytorch.org/whl/cu121

# ------------------------------------------------------------
# Ditto dependencies
# ------------------------------------------------------------
RUN ${CONDA_DIR}/envs/ditto/bin/python -m pip install \
    numpy==2.0.1 \
    audioread==3.0.1 \
    cffi==1.17.1 \
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
    packaging==24.2 \
    pillow==11.0.0 \
    platformdirs==4.3.6 \
    pooch==1.8.2 \
    pycparser==2.22 \
    pyyaml==6.0.2 \
    requests==2.32.3 \
    rembg==2.0.69 \
    scikit-image==0.25.0 \
    scikit-learn==1.6.0 \
    scipy==1.15.0 \
    soundfile==0.13.0 \
    soxr==0.5.0.post1 \
    threadpoolctl==3.5.0 \
    tifffile==2024.12.12 \
    tqdm==4.67.1

# NumPy 2.x is required by the bundled Ditto code (np.atan2 alias).
# The TRT config does not require the optional MediaPipe/ONNX Runtime Python paths.
RUN ${CONDA_DIR}/envs/ditto/bin/python - <<'PY'
import numpy as np
print("NumPy:", np.__version__)
assert np.__version__ == "2.0.1"
assert hasattr(np, "atan2")
print("np.atan2 OK:", np.atan2(1.0, 1.0))
PY

# ------------------------------------------------------------
# TensorRT 8.6.1
# ------------------------------------------------------------

# Native libs + Python bindings
RUN ${CONDA_DIR}/envs/ditto/bin/python -m pip install \
    tensorrt-bindings==8.6.1 \
    tensorrt-libs==8.6.1 \
    --extra-index-url https://pypi.nvidia.com

# TensorRT Python frontend
# no-build-isolation is important for TensorRT 8.6.1
RUN ${CONDA_DIR}/envs/ditto/bin/python -m pip install \
    --no-build-isolation \
    --no-deps \
    tensorrt==8.6.1 \
    --extra-index-url https://pypi.nvidia.com

RUN ${CONDA_DIR}/envs/ditto/bin/python -m pip install \
    polygraphy \
    colored

# ------------------------------------------------------------
# Verify CUDA / cuDNN / TensorRT
# ------------------------------------------------------------
RUN ${CONDA_DIR}/envs/ditto/bin/python - <<'PY'
import torch
import tensorrt as trt

print("================================")
print("PyTorch :", torch.__version__)
print("CUDA    :", torch.version.cuda)
print("cuDNN   :", torch.backends.cudnn.version())
print("TensorRT:", trt.__version__)
print("================================")

cudnn = torch.backends.cudnn.version()

assert torch.version.cuda.startswith("12.1"), torch.version.cuda
assert cudnn is not None
assert str(cudnn).startswith("8"), cudnn
assert trt.__version__.startswith("8.6.1"), trt.__version__
PY

# ------------------------------------------------------------
# Application source
# core/ 포함해서 프로젝트 전체 COPY
# ------------------------------------------------------------
COPY . /app

RUN mkdir -p /app/data

# ------------------------------------------------------------
# Runtime
# ------------------------------------------------------------
ENV PATH=${CONDA_DIR}/envs/app/bin:${PATH}
ENV DITTO_PYTHON=${CONDA_DIR}/envs/ditto/bin/python
ENV APP_HOST=0.0.0.0
ENV APP_PORT=8002
ENV APP_RELOAD=0
ENV DATA_DIR=/app/data
ENV PYTHONUNBUFFERED=1

EXPOSE 8002

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/opt/conda/envs/app/bin/python", "app.py"]
