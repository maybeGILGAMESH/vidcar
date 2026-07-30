# Vidcar — платформа дорожной видеоаналитики

Репозиторий: [maybeGILGAMESH/vidcar](https://github.com/maybeGILGAMESH/vidcar)

Локальный pilot-стек: FastAPI, PostGIS, RabbitMQ, Keycloak, MinIO (dev), Celery workers, Next.js web, Expo mobile, GPU-worker baseline.

## Быстрый старт

```bash
cp infra/compose/.env.example infra/compose/.env
make validate
make preflight
docker compose -f infra/compose/compose.yaml --env-file infra/compose/.env \
  --profile dev --profile gpu up -d --build
make smoke
```

Подробнее для второй ноды: [`docs/deploy_another_node.md`](docs/deploy_another_node.md).

## Команды

| Команда | Назначение |
|---------|------------|
| `make validate` | Статическая проверка каркаса |
| `make preflight` | Python/GPU/Docker/модели |
| `make up` / `make down` | Compose up/down |
| `make smoke` | HTTP health + GPU mock smoke |
| `make test` | pytest unit/gpu/recovery/load |
| `./scripts/run_demo.sh` | Annotated MP4 + progress GIF |

## Документы

- `docs/implementation_plan.md`
- `docs/architecture_decisions.md`
- `docs/assumptions_and_blockers.md`
- `docs/acceptance_tests.md`
- `docs/vehicle_size_taxonomy.md`
- `docs/deploy_another_node.md`
- `agent_implementation_brief.md` / `human_operator_setup.md`

## Модели и OCR

Production-воркер читает только approved registry.  
Пайплайн `vehicle-pipeline-0.1.0` использует уже загруженные baseline-веса.  
OCR: **latin** + локальный перевод lookalike-букв в русский номерной алфавит.  
Cyrillic HF OCR и DeepStream — не часть текущего pilot-коммита.

## Секреты

В Git не класть:

- `infra/compose/.env`, корневой `.env`
- пароли Postgres/RabbitMQ/Keycloak/MinIO/S3
- GitHub tokens, private keys

Шаблоны: `.env.example`, `infra/compose/.env.example`.

## Edge URL (локально)

После `compose up`: [http://127.0.0.1:8080/](http://127.0.0.1:8080/)
