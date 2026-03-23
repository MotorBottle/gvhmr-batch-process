FROM nvidia/cuda:12.1.0-devel-ubuntu22.04

ARG TORCH_CUDA_ARCH_LIST="7.5;8.0;8.6;8.9"

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV GVHMR_ROOT=/app/gvhmr
ENV CUDA_HOME=/usr/local/cuda-12.1
ENV PATH=${CUDA_HOME}/bin:${PATH}
ENV LD_LIBRARY_PATH=${CUDA_HOME}/lib64:${LD_LIBRARY_PATH}
ENV TORCH_CUDA_ARCH_LIST=${TORCH_CUDA_ARCH_LIST}

RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    ffmpeg \
    git \
    libglib2.0-0 \
    libgl1 \
    libgomp1 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    ninja-build \
    python3-pip \
    python3-tk \
    python3.10 \
    python3.10-dev \
    unzip \
    wget \
    && rm -rf /var/lib/apt/lists/*

RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.10 1 && \
    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.10 1

WORKDIR /app

COPY third_party/GVHMR /app/gvhmr
COPY packages/common /app/packages/common
COPY packages/gvhmr_runner /app/packages/gvhmr_runner
COPY services/worker /app/services/worker

RUN python -m pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir torch==2.3.0 torchvision==0.18.0 --index-url https://download.pytorch.org/whl/cu121 && \
    pip install --no-cache-dir fvcore iopath && \
    pip install --no-cache-dir --no-index pytorch3d -f https://dl.fbaipublicfiles.com/pytorch3d/packaging/wheels/py310_cu121_pyt230/download.html && \
    pip install --no-cache-dir chumpy --no-build-isolation

RUN grep -vE '^(--extra-index-url|torch==|torchvision==|pytorch3d|chumpy$)' /app/gvhmr/requirements.txt > /tmp/gvhmr-worker-requirements.txt && \
    pip install --no-cache-dir -r /tmp/gvhmr-worker-requirements.txt

RUN test -f /app/gvhmr/third-party/DPVO/setup.py && \
    mkdir -p /app/gvhmr/third-party/DPVO/thirdparty && \
    wget -q https://gitlab.com/libeigen/eigen/-/archive/3.4.0/eigen-3.4.0.zip -O /tmp/eigen-3.4.0.zip && \
    unzip -q /tmp/eigen-3.4.0.zip -d /app/gvhmr/third-party/DPVO/thirdparty && \
    rm -f /tmp/eigen-3.4.0.zip && \
    pip install --no-cache-dir torch-scatter -f https://data.pyg.org/whl/torch-2.3.0+cu121.html && \
    pip install --no-cache-dir numba pypose && \
    pip install --no-cache-dir --no-build-isolation -e /app/gvhmr/third-party/DPVO

RUN pip install --no-cache-dir -e /app/gvhmr && \
    pip install --no-cache-dir -e /app/packages/common -e /app/packages/gvhmr_runner -e /app/services/worker

RUN mkdir -p \
    /app/gvhmr/inputs/checkpoints/gvhmr \
    /app/gvhmr/inputs/checkpoints/hmr2 \
    /app/gvhmr/inputs/checkpoints/vitpose \
    /app/gvhmr/inputs/checkpoints/yolo \
    /app/gvhmr/inputs/checkpoints/dpvo \
    /app/gvhmr/inputs/checkpoints/body_models/smpl \
    /app/gvhmr/inputs/checkpoints/body_models/smplx \
    /app/gvhmr/outputs/demo \
    /var/lib/gvhmr-batch-process

CMD ["python", "-m", "gvhmr_batch_worker.main"]
