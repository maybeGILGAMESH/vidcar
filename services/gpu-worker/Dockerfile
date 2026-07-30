FROM python:3.12.8-slim-bookworm

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    MODEL_APPROVED_ROOT=/opt/vehicle-ai/model-registry/approved

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
  && rm -rf /var/lib/apt/lists/*

COPY apps/api/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt opencv-python-headless pyyaml

COPY packages /app/packages
COPY services /app/services
COPY models/manifests /app/models/manifests

CMD ["python", "-c", "import time; print('gpu-worker image ready; waiting for jobs'); time.sleep(3600)"]
