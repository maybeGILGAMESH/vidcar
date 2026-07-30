# Задание агенту: спланировать и собрать систему дорожной видеоаналитики

**Роль:** ведущий архитектор и агент сборки.  
**Входной операторский документ:** `human_operator_setup.md`.  
**Входные параметры:** `operator_inputs.yaml`.  
**Целевая конфигурация:** две GPU-ноды с расширением до четырёх GPU-воркеров.

---

# Главное правило запуска

Не начинать реализацию сразу.

После чтения этого документа агент обязан сначала создать:

```text
docs/implementation_plan.md
docs/architecture_decisions.md
docs/assumptions_and_blockers.md
docs/acceptance_tests.md
```

До создания этих документов агент не должен:

- устанавливать production-сервисы;
- менять существующую БД;
- открывать сетевые порты;
- загружать новые модели;
- удалять файлы;
- менять конфигурацию 60-ТБ хранилища;
- начинать длительное обучение моделей.

План должен быть пригоден для проверки человеком.

---

# Что агент должен прочитать

Обязательные входы:

```text
human_operator_setup.md
operator_inputs.yaml
operator-evidence/main-node.txt
operator-evidence/worker-node.txt
sha256sums-2026-07-29.txt
```

Если обязательного входа нет, агент фиксирует блокер и предлагает безопасную временную замену.

---

# Цель системы

Создать платформу, которая:

- предоставляет веб-приложение;
- предоставляет мобильное приложение;
- авторизует до 60 пользователей;
- отображает карту;
- сохраняет GPS и точность координат;
- сохраняет необязательное направление камеры;
- принимает до десяти заметок на видео;
- загружает видео размером 3–4 ГБ;
- объединяет несколько видео в одну съёмку;
- сохраняет исходники;
- запускает асинхронную GPU-обработку;
- считает автомобили;
- классифицирует размер транспорта;
- распознаёт номера;
- создаёт сжатую копию;
- выдаёт отчёт через API;
- работает на двух GPU;
- расширяется до четырёх GPU;
- не повреждает данные при параллельной записи;
- восстанавливает задания после перезапуска.

---

# Базовая архитектура

## Main-нода

Main-нода размещает:

```text
reverse proxy
web application
fastapi
keycloak
postgresql
rabbitmq
scheduler
probe worker
result-writer
monitoring
gpu worker main
object storage client or gateway
```

GPU-воркер на main-ноде должен быть изолирован так же, как удалённый worker. Он не получает прямой доступ к PostgreSQL.

## Worker-нода

Worker-нода размещает:

```text
gpu worker 02
deepstream
gstreamer
tensorrt
ffmpeg
nvenc
model cache
scratch storage
monitoring agent
```

## Масштабирование

Добавление третьего и четвёртого GPU выполняется запуском дополнительных consumers:

```text
gpu-main
gpu-02
gpu-03
gpu-04
```

API, схема БД и формат результата при этом не меняются.

---

# Неподлежащие изменению ограничения

- видео не хранится в PostgreSQL;
- API не проксирует полный файл 3–4 ГБ;
- загрузка выполняется multipart напрямую в объектное хранилище;
- GPU-воркеры не имеют реквизитов PostgreSQL;
- единственный `result-writer` публикует результаты;
- исходники не перезаписываются;
- каждый объект имеет уникальный ключ;
- каждый результат привязан к версии пайплайна;
- повторная доставка сообщения не создаёт дубликат;
- обработка выполняется потоково;
- все кадры не сохраняются на диск;
- production-модели читаются только из `approved`;
- TensorRT engine не является главным исходником модели;
- ONNX или исходные Paddle-веса сохраняются;
- внешняя БД изначально подключена только как отключённый adapter stub.

---

# Временная внешняя интеграция

Текущие адреса:

```text
http://file-ai-srv.rudn.su:8000
http://file-ai.rudn.su
```

Подсказка логина:

```text
admin@localhost.local
```

Текущее состояние:

```text
dns_nxdomain
```

Агент должен реализовать interface:

```python
from typing import protocol


class external_database_adapter(protocol):
    def healthcheck(self) -> dict:
        """возвращает состояние интеграции"""

    def fetch_reference_data(self, query: dict) -> list[dict]:
        """получает справочные данные"""

    def publish_result(self, payload: dict) -> dict:
        """публикует результат, если запись разрешена"""
```

Первая реализация:

```text
stub_external_database_adapter
```

Поведение:

```json
{
  "status": "not_configured",
  "state": "dns_nxdomain",
  "retryable": false
}
```

HTTP-адрес веб-интерфейса нельзя превращать в PostgreSQL DSN.

---

# Технологический стек

| Слой | Компонент |
|---|---|
| Web | Next.js или React |
| Mobile | React Native |
| Карта | MapLibre |
| API | FastAPI |
| Авторизация | Keycloak |
| БД | PostgreSQL и PostGIS |
| Очередь | RabbitMQ и Celery |
| Файлы | S3-совместимое хранилище |
| Потоковое видео | GStreamer |
| GPU pipeline | DeepStream 9.1 |
| Детекция | PP-YOLOE PPVehicle |
| Трекинг | ByteTrack, затем NvDCF |
| Классификация | отдельный компактный классификатор |
| Номерной detector | отдельная модель `plate` |
| OCR | PaddleOCR с ограниченным словарём |
| Ускорение | ONNX и TensorRT |
| Сжатие | FFmpeg и NVENC |
| Мониторинг | Prometheus, Grafana, Loki |
| Контейнеры | Docker Compose |

Kubernetes не требуется на первом этапе.

---

# Репозиторий

```text
apps/
  web/
  mobile/
  api/

services/
  scheduler/
  probe-worker/
  gpu-worker/
  result-writer/
  maintenance/
  external-db-adapter/

packages/
  contracts/
  schemas/
  model-manifest/
  api-client/
  common/

infra/
  compose/
  nginx/
  postgres/
  rabbitmq/
  keycloak/
  monitoring/
  storage/

models/
  manifests/
  validation/

migrations/

docs/
  implementation_plan.md
  architecture_decisions.md
  assumptions_and_blockers.md
  acceptance_tests.md
  runbooks/

tests/
  unit/
  integration/
  recovery/
  load/
  fixtures/
```

---

# Что должно быть в плане агента

`docs/implementation_plan.md` должен содержать:

- фактическое состояние обеих нод;
- зависимости и версии;
- блокеры;
- архитектурные этапы;
- результат каждого этапа;
- изменяемые файлы;
- команды проверки;
- критерий готовности;
- план отката;
- риски;
- действия, которые нужны от человека.

Не указывать фиктивные сроки. Использовать зависимости, сложность, блокеры и проверяемые результаты.

---

# Пайплайн обработки

```text
video uploaded
  |
  v
probe
  |
  v
job queued
  |
  v
one gpu worker claims job
  |
  v
stream decode
  |
  v
vehicle detection
  |
  v
tracking
  |
  v
line crossing
  |
  v
best frame selection
  |
  +--> size classification
  |
  +--> plate detection
  |      |
  |      v
  |     ocr
  |
  v
aggregation
  |
  v
compressed video
  |
  v
immutable result manifest
  |
  v
result-writer
  |
  v
postgres transaction
```

---

# Распределение работы между двумя GPU

Каждый GPU-воркер получает одно видео целиком.

Не разделять одно видео по произвольным временным кускам на две GPU в первой версии.

```text
gpu-main -> video-a
gpu-02   -> video-b
```

После завершения свободный worker берёт следующее видео.

Для съёмки из трёх видео:

```text
первая волна:
gpu-main -> video-a
gpu-02   -> video-b

вторая волна:
свободный gpu -> video-c
```

После benchmark агент может предложить больший параллелизм, но только с измерениями.

---

# Модели

## Детектор транспорта

Начальный вход:

```text
mot_ppyoloe_l_36e_ppvehicle.zip
```

Агент должен:

- проверить запуск;
- измерить FPS;
- проверить качество;
- подготовить ONNX;
- собрать TensorRT engine на каждой ноде;
- сохранить build metadata.

## Трекинг

Сравнить ByteTrack и DeepStream NvDCF по:

- разрывам трека;
- повторному подсчёту;
- скорости;
- памяти;
- перекрытиям.

## Классификатор размера

Классы:

```text
light
medium
heavy
unknown
```

Сначала создать:

```text
docs/vehicle_size_taxonomy.md
```

До согласования taxonomy обучение не начинать.

## Детектор номера

Отдельная модель:

```text
plate
```

Нужно создать датасет, validator разметки, обучить detector и измерить recall.

## OCR

Стартовая модель:

```text
cyrillic_pp-ocrv5_mobile_rec
```

Финальный алфавит:

```text
0123456789abcehkmoptxy
```

Сохранять исходную строку, нормализованную строку, confidence и голосование по кадрам.

---

# Реестр моделей

```yaml
pipeline_version: vehicle-pipeline-0.1.0

models:
  vehicle_detector:
    name: ppvehicle-detector
    version: 0.1.0
    object_key: replace_me
    sha256: replace_me

  vehicle_classifier:
    name: vehicle-size
    version: 0.1.0
    object_key: replace_me
    sha256: replace_me

  plate_detector:
    name: russian-plate-detector
    version: 0.1.0
    object_key: replace_me
    sha256: replace_me

  plate_ocr:
    name: russian-plate-ocr
    version: 0.1.0
    object_key: replace_me
    sha256: replace_me
```

Реализовать проверку SHA-256, локальный cache, rollback и запрет `latest`.

---

# Безопасная запись

GPU worker создаёт:

```text
tmp/{job_id}/{worker_id}/...
results/{video_id}/{pipeline_version}/...
derived/{video_id}/{pipeline_version}/...
```

GPU worker не может:

```text
delete originals
overwrite originals
update database rows
modify bucket policy
read user secrets
```

`result-writer` проверяет manifest и SHA-256, затем одной транзакцией публикует полный результат.

---

# Минимальные таблицы и ограничения

```text
users
roles
surveys
survey_notes
videos
processing_jobs
processing_attempts
pipeline_versions
model_versions
vehicle_tracks
vehicle_events
vehicle_classifications
plate_observations
processing_results
audit_log
```

```sql
unique (video_id, pipeline_version)
```

```sql
unique (video_id, pipeline_version, result_type)
```

Статусы:

```text
created
uploading
uploaded
queued
claimed
processing
uploading_results
awaiting_finalize
completed
failed_retryable
failed_terminal
cancelled
```

---

# API

Минимальные endpoints:

```text
post /api/v1/surveys
post /api/v1/videos/upload-sessions
post /api/v1/videos/{video_id}/complete-upload
get  /api/v1/videos/{video_id}
get  /api/v1/videos/{video_id}/result
get  /api/v1/videos/{video_id}/download
get  /api/v1/integrations/external-database/health
```

Для списков обязательны pagination, filtering, sorting, authorization и audit.

---

# Мобильное приложение

Спланировать:

- OIDC login;
- MapLibre;
- GPS;
- точность GPS;
- направление камеры;
- ручную корректировку точки;
- до десяти заметок;
- выбор нескольких видео;
- multipart upload;
- возобновление после обрыва;
- фоновую очередь загрузки;
- статус обработки;
- просмотр результата.

Постоянные S3-ключи в приложение не встраиваются.

---

# Хранилище

Bucket-структура:

```text
vehicle-originals
vehicle-derived
vehicle-results
vehicle-models
vehicle-temporary
vehicle-backups
```

Проверить versioning, Object Lock, backup, RAID или erasure coding, скорость и поведение при заполнении.

---

# Безопасность

Роли:

```text
api-service
result-writer
gpu-worker
backup-service
monitoring
human-admin
```

Сеть:

```text
internet -> reverse proxy
reverse proxy -> api and web
api -> postgres, rabbitmq, s3, keycloak
gpu worker -> rabbitmq, s3, monitoring
gpu worker -x-> postgres
postgres -x-> internet
rabbitmq -x-> internet
```

Секреты не сохранять в Git и не выводить в логи.

---

# Тесты до production

Проверить:

- два worker берут разные задания;
- повторное событие не создаёт дубликат;
- worker выключен во время обработки;
- main-нода выключена после готового manifest;
- RabbitMQ и PostgreSQL перезапущены;
- multipart upload прерван и продолжен;
- неверный checksum отклонён;
- original нельзя перезаписать;
- неверная модель или SHA-256 блокирует старт;
- rollback manifest работает;
- очередь из двадцати файлов обрабатывается;
- API остаётся отзывчивым.

---

# Приёмочные критерии пилота

- пользователь входит в систему;
- мобильное приложение сохраняет точку;
- видео 4 ГБ загружается и возобновляется;
- две GPU обрабатывают разные видео;
- одно видео не считается дважды;
- подсчёт по линии работает;
- классы транспорта выдаются;
- номер сохраняется с confidence;
- сжатая копия создаётся;
- оригинал не перезаписывается;
- результат доступен через API;
- перезапуск worker не теряет задачу;
- перезапуск main-ноды не повреждает данные;
- backup PostgreSQL восстанавливается;
- внешняя БД остаётся в режиме stub;
- все модели зафиксированы по версии и SHA-256.

---

# Первый ответ агента после чтения

Агент должен выдать человеку:

```text
что найдено
что неизвестно
какие решения предлагаются
какие блокеры есть
план этапов
критерии каждого этапа
какие действия нужны от человека
```

До просмотра человеком `implementation_plan.md` агент не начинает production-сборку, если не получено явное разрешение продолжить автоматически.
