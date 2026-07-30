# GPU worker: CUDA runtime + Paddle Inference ensemble (detector/OCR/attributes).
FROM nvidia/cuda:12.6.3-cudnn-runtime-ubuntu22.04

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/app/services/gpu-worker \
    MODEL_APPROVED_ROOT=/opt/vehicle-ai/model-registry/approved \
    MODEL_MANIFEST=/app/models/manifests/vehicle-pipeline-0.1.0.yaml \
    DETECTOR_BACKEND=paddle \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 \
      python3-pip \
      python3-venv \
      ffmpeg \
      libgl1 \
      libglib2.0-0 \
      libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3 /usr/bin/python

COPY apps/api/requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir --upgrade pip \
  && pip3 install --no-cache-dir -r /tmp/requirements.txt \
  && pip3 install --no-cache-dir \
      "psycopg[binary]>=3.2,<4" \
      "opencv-python-headless>=4.8,<5" \
      "PyYAML>=6.0,<7" \
      celery \
      redis \
  && pip3 install --no-cache-dir paddlepaddle-gpu==3.0.0 \
      -i https://www.paddlepaddle.org.cn/packages/stable/cu126/

COPY packages /app/packages
COPY services /app/services
COPY models/manifests /app/models/manifests

WORKDIR /app/services/gpu-worker
CMD ["celery", "-A", "gpu_worker.tasks.celery_app", "worker", "--loglevel=INFO", "-Q", "gpu", "--concurrency=1"]
