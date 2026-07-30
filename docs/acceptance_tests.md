# Приёмочные тесты

Статусы: `READY` — можно выполнять; `BLOCKED` — отсутствует prerequisite; `PLANNED` — относится к будущему этапу.

## Этап 1

- `READY` `make validate` подтверждает обязательные документы, normalized inputs, каталоги, placeholders и исполняемые scripts.
- `READY` исходные `agent_implementation_brief (1).md` и `human_operator_setup (1).md` существуют после создания normalized copies.
- `READY` `.env.example` и `operator_inputs.yaml` не содержат реальных паролей, secret keys или DB DSN.
- `READY` worker evidence явно помечен как заглушка.
- `READY` `make bootstrap` завершается ненулевым кодом при отсутствии Docker или обязательных inputs.
- `READY` `make up` и `make smoke` не заявляют успех при отсутствии compose/future components.

## Upload и данные

- `PLANNED` пользователь создаёт survey и добавляет не более десяти notes на видео.
- `BLOCKED` файл 4 ГБ загружается multipart напрямую в S3 и возобновляется после обрыва.
- `BLOCKED` original нельзя перезаписать; неверный checksum отклоняется.
- `PLANNED` несколько видео объединяются в одну съёмку без слияния originals.

## Очередь и восстановление

- `BLOCKED` два workers получают разные видео.
- `PLANNED` повторное сообщение не создаёт дубликат результата.
- `BLOCKED` выключение worker возвращает незавершённую задачу в обработку.
- `PLANNED` рестарт RabbitMQ/PostgreSQL не теряет завершённый manifest.
- `PLANNED` выключение main после загрузки manifest не создаёт частичный результат.

## GPU pipeline

- `BLOCKED` detection, tracking и line crossing работают на утверждённом наборе.
- `BLOCKED` classifier выдаёт `light|medium|heavy|unknown` по согласованной taxonomy.
- `BLOCKED` plate detector/OCR сохраняют raw, normalized, confidence и frame voting.
- `BLOCKED` compressed derivative создаётся, original не изменяется.
- `BLOCKED` неверная версия модели или SHA-256 блокирует worker; rollback manifest работает.

## API, клиенты и безопасность

- `PLANNED` OIDC login и role checks работают для web/mobile.
- `PLANNED` mobile сохраняет GPS, accuracy, optional direction и ручную коррекцию.
- `PLANNED` результат доступен через API с pagination/filtering/sorting/audit.
- `PLANNED` GPU worker не имеет DB credentials и сетевого доступа к PostgreSQL.
- `READY` external DB остаётся `enabled: false`, `mode: stub`.

## Нагрузка

- `BLOCKED` очередь из 20 файлов обрабатывается без потери/дублирования.
- `BLOCKED` API остаётся отзывчивым во время двух одновременных GPU jobs.
- `BLOCKED` измерены FPS, GPU/RAM/scratch utilization и storage throughput.
