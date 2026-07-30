# Допущения и блокеры

Дата фиксации: 2026-07-30.

## Подтверждено

- Текущая машина — `Node7`, Ubuntu 24.04.3 LTS.
- Доступна одна NVIDIA GeForce RTX 3090 24 GiB.
- NVIDIA driver работает; Docker отсутствует.
- Исходные документы присутствуют и сохранены без изменений.
- Внешняя БД должна оставаться отключённым stub.

## Допущения

- `Node7` временно считается main-нодой.
- Адрес `10.162.1.93` является полученным по DHCP локальным адресом, а не утверждённым production endpoint.
- `/srv/vehicle-ai/scratch` — целевой путь, но его наличие, объём и права пока не подтверждены.
- Целевая ёмкость S3 — 60 ТБ, однако endpoint и защитные свойства пока не существуют/не подтверждены.
- До benchmark один worker берёт одно видео; параллелизм внутри GPU не обещается.
- Все значения `replace_me`, `null` и `not_configured` являются блокирующими placeholders.

## Блокеры

| Блокер | Влияние | Безопасное временное состояние | Требуемое действие |
|---|---|---|---|
| Docker/Compose отсутствуют | Нельзя поднять полный Compose-стек | Local `make smoke`/`make test` работают; `make up` блокируется | Установить Docker+Compose+NVIDIA toolkit с sudo |
| Worker-нода отсутствует | Нет проверки двух GPU | Compose profile `worker-node` готов | Предоставить ноду и evidence |
| S3 60 ТБ отсутствует | Нет production multipart/immutability | MinIO profile `dev` + remote S3 placeholders | Передать endpoint и политики |
| `/opt/.../approved` root-owned | Нельзя писать системный registry без sudo | Local `.runtime/model-registry/approved` + hardlinks | `chown`/`rsync` оператором при необходимости |
| Cyrillic HF OCR отсутствует | Нет Russian production OCR | Latin/baseline allowlist, `production_russian_ocr=false` | Скачать и утвердить отдельно |
| Taxonomy не утверждена | Нельзя обучать size classifier | Fallback/unknown | Согласовать определения |
| Тестовые данные заказчика отсутствуют | Нельзя измерить качество моделей | Synthetic fixture smoke | Передать видео/expected report |
| External DB credentials/schema отсутствуют | Нет интеграции | Disabled stub | Получить у администратора |

## Снято с блокеров (локально)

- `sha256sums-2026-07-29.txt` сформирован.
- Baseline-модели продвинуты в локальный approved с metadata.
- `vehicle-pipeline-0.1.0` manifest валидируется.
- Unit/GPU/recovery/load: 17 passed, 1 skipped (нет Postgres env).
