# Развёртывание на другой ноде

Дата: 2026-07-30.

## Что есть в Git

Исходники платформы: API, workers, web/mobile, Compose, миграции, manifests моделей, тесты и скрипты.

## Что НЕ приходит из Git

| Артефакт | Где взять |
|----------|-----------|
| `.env` / `infra/compose/.env` | скопировать из `*.env.example` и заполнить |
| Docker + NVIDIA Container Toolkit | установить на ноде |
| Модели в `/opt/vehicle-ai/...` или `.runtime/model-registry/approved` | staging → approved по `human_operator_setup.md` |
| Видео-фикстуры / demo GIF | скачать отдельно или `./scripts/run_demo.sh` после появления роликов |
| Секреты S3 / DB / Keycloak | только secret-файлы вне репозитория |
| DeepStream NGC-образ | `docker pull nvcr.io/nvidia/deepstream:9.1-samples-multiarch` |

## Минимальный bootstrap на новой ноде

```bash
git clone https://github.com/maybeGILGAMESH/vidcar.git
cd vidcar

# Python 3.10+
conda create --prefix ./.venv python=3.10 pip -y
conda activate ./.venv
pip install -r apps/api/requirements.txt opencv-python-headless pyyaml

# Node (web/mobile, по необходимости)
cd packages/api-client && npm install && npm run build && cd ../..
cd apps/web && npm install && cd ../..

# Compose env
cp infra/compose/.env.example infra/compose/.env
# отредактировать пароли/endpoints; для 60 ТБ S3 заменить MinIO endpoint

# Модели: положить approved weights + metadata рядом с manifests
# см. models/manifests/vehicle-pipeline-0.1.0.yaml

make validate
make preflight
docker compose -f infra/compose/compose.yaml --env-file infra/compose/.env \
  --profile dev --profile gpu up -d --build
make smoke
```

## Сети Docker и VPN

Если VPN занимает стандартные Docker-пулы, задайте в `/etc/docker/daemon.json` непересекающиеся `bip` / `default-address-pools` или используйте явные subnet в `infra/compose/compose.yaml` (сейчас `172.30.10.0/24`…`172.30.13.0/24`).

## GPU worker

- Не получает credentials PostgreSQL.
- Читает только approved model registry.
- OCR сейчас: latin baseline + локальный lookalike-перевод в русский номерной алфавит (`production_russian_ocr: false`).
- DeepStream / полноценный Paddle inference — отдельный этап после рабочего Compose.

## Worker-нода (вторая машина)

1. Клонировать тот же commit.
2. Скопировать `approved/` с checksum verify.
3. Запустить профиль `worker-node` Compose против общего RabbitMQ/S3.
4. Не открывать PostgreSQL с worker-ноды.

## Проверки готовности

```bash
make preflight
curl -fsS http://127.0.0.1:8080/healthz
curl -fsS http://127.0.0.1:8080/api/v1/integrations/external-database/health
./scripts/run_demo.sh   # нужен opencv + ffmpeg + fixture videos
```
