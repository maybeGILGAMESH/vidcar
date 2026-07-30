FROM python:3.12.8-slim-bookworm

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

COPY apps/api/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY packages /app/packages
COPY services /app/services
COPY apps/api /app/apps/api

# Default keeps container alive for compose health; services override the command.
CMD ["python", "-c", "import time; print('python worker image ready'); time.sleep(3600)"]
