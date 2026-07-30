# Инструкция человеку: подготовка серверов, моделей, хранилища и подключения БД

**Назначение:** этот файл выполняет оператор или владелец инфраструктуры до запуска агента сборки.  
**Дата проверки ссылок:** 29 июля 2026 года.  
**Целевая конфигурация:** две NVIDIA GPU-ноды, одна из них main-нода.  
**Расширение:** до четырёх GPU-воркеров без изменения основной схемы.

---

## Что должен сделать человек

До передачи задачи агенту необходимо:

- подтвердить характеристики двух компьютеров;
- подготовить центральное хранилище 60 ТБ;
- создать каталоги для моделей и временных файлов;
- скачать исходные модели только из указанных источников;
- сохранить модели внутри инфраструктуры владельца;
- посчитать SHA-256;
- заполнить файл входных данных для агента;
- получить реальные реквизиты базы данных у администратора;
- оставить текущие веб-адреса как отключённую временную заглушку;
- не передавать агенту административный пароль в открытом виде.

Агент не должен самостоятельно искать произвольные модели и загружать их напрямую в production.

---

# Распределение двух компьютеров

## Main-нода

На main-ноде будут работать:

- веб-интерфейс;
- backend API;
- Keycloak;
- PostgreSQL;
- RabbitMQ;
- `result-writer`;
- планировщик;
- мониторинг;
- один GPU-воркер;
- доступ к центральному хранилищу 60 ТБ;
- локальный NVMe 1 ТБ для временной обработки.

Запишите сведения:

```yaml
main_node:
  hostname: replace_me
  ip_address: replace_me
  operating_system: ubuntu_24_04
  gpu_model: replace_me
  gpu_memory_gb: replace_me
  cpu_cores: replace_me
  ram_gb: replace_me
  scratch_disk: /srv/vehicle-ai/scratch
  storage_mount_or_endpoint: replace_me
```

## Worker-нода

На worker-ноде будут работать:

- второй GPU-воркер;
- DeepStream или GStreamer;
- TensorRT;
- Paddle-модели на этапе прототипа;
- FFmpeg и NVENC;
- локальный NVMe 1 ТБ;
- агент мониторинга.

```yaml
worker_node:
  hostname: replace_me
  ip_address: replace_me
  operating_system: ubuntu_24_04
  gpu_model: replace_me
  gpu_memory_gb: replace_me
  cpu_cores: replace_me
  ram_gb: replace_me
  scratch_disk: /srv/vehicle-ai/scratch
  storage_endpoint: replace_me
```

---

# Проверка оборудования

Выполнить на каждой ноде:

```bash
# проверяем gpu и драйвер
nvidia-smi

# проверяем систему
cat /etc/os-release
uname -r

# проверяем диски
lsblk -o name,size,type,fstype,mountpoint
df -h

# проверяем сеть
ip -br address
ip route

# проверяем docker
docker version
```

Сохранить вывод в файлы:

```text
operator-evidence/main-node.txt
operator-evidence/worker-node.txt
```

---

# Создание каталогов

На обеих GPU-нодах:

```bash
# создаём каталоги приложения
sudo mkdir -p /opt/vehicle-ai/model-registry/staging
sudo mkdir -p /opt/vehicle-ai/model-registry/approved
sudo mkdir -p /opt/vehicle-ai/models
sudo mkdir -p /opt/vehicle-ai/engines
sudo mkdir -p /srv/vehicle-ai/scratch
sudo mkdir -p /var/log/vehicle-ai
sudo mkdir -p /etc/vehicle-ai/secrets
```

Создать системного пользователя:

```bash
# создаём системного пользователя без входа
sudo useradd \
  --system \
  --create-home \
  --home-dir /var/lib/vehicle-ai \
  --shell /usr/sbin/nologin \
  vehicle-ai
```

Назначить права:

```bash
# назначаем владельца рабочих каталогов
sudo chown -r vehicle-ai:vehicle-ai /opt/vehicle-ai
sudo chown -r vehicle-ai:vehicle-ai /srv/vehicle-ai
sudo chown -r vehicle-ai:vehicle-ai /var/log/vehicle-ai

# закрываем каталог секретов
sudo chown root:vehicle-ai /etc/vehicle-ai/secrets
sudo chmod 750 /etc/vehicle-ai/secrets
```

---

# Что скачать человеку

## Репозиторий PaddleDetection

Официальный репозиторий:

```text
https://github.com/PaddlePaddle/PaddleDetection
```

Для воспроизводимости использовать ветку `release/2.9`:

```bash
# скачиваем зафиксированную ветку paddledetection
cd /opt/vehicle-ai/model-registry/staging

git clone \
  --branch release/2.9 \
  --depth 1 \
  https://github.com/PaddlePaddle/PaddleDetection.git
```

После загрузки сохранить commit:

```bash
# записываем commit репозитория
cd /opt/vehicle-ai/model-registry/staging/PaddleDetection
git rev-parse head | tee ../paddledetection-release-2.9.commit
```

---

## Базовая модель детекции и трекинга транспорта

Рекомендуемый первый вариант для прототипа:

```text
https://bj.bcebos.com/v1/paddledet/models/pipeline/mot_ppyoloe_l_36e_ppvehicle.zip
```

Скачать:

```bash
# скачиваем базовую модель транспорта
cd /opt/vehicle-ai/model-registry/staging

curl -fL \
  https://bj.bcebos.com/v1/paddledet/models/pipeline/mot_ppyoloe_l_36e_ppvehicle.zip \
  -o mot_ppyoloe_l_36e_ppvehicle.zip
```

Эта модель используется как стартовая для обнаружения транспорта, трекинга и проверки конвейера. Она объединяет транспорт в один класс `vehicle`.

---

## Модель PPVehicle9cls для эксперимента

Модель на девять категорий:

```text
https://paddledet.bj.bcebos.com/models/mot_ppyoloe_l_36e_ppvehicle9cls.pdparams
```

Облегчённая версия:

```text
https://paddledet.bj.bcebos.com/models/mot_ppyoloe_s_36e_ppvehicle9cls.pdparams
```

Скачать обе для сравнения:

```bash
# скачиваем веса ppvehicle9cls
cd /opt/vehicle-ai/model-registry/staging

curl -fL \
  https://paddledet.bj.bcebos.com/models/mot_ppyoloe_l_36e_ppvehicle9cls.pdparams \
  -o mot_ppyoloe_l_36e_ppvehicle9cls.pdparams

curl -fL \
  https://paddledet.bj.bcebos.com/models/mot_ppyoloe_s_36e_ppvehicle9cls.pdparams \
  -o mot_ppyoloe_s_36e_ppvehicle9cls.pdparams
```

Эти веса нужны только для эксперимента. Они не дают готовое разделение `light`, `medium`, `heavy`, `unknown`.

---

## Базовая модель атрибутов автомобиля

Официальная стартовая модель:

```text
https://bj.bcebos.com/v1/paddledet/models/pipeline/vehicle_attribute_model.zip
```

Скачать:

```bash
# скачиваем базовую модель атрибутов
cd /opt/vehicle-ai/model-registry/staging

curl -fL \
  https://bj.bcebos.com/v1/paddledet/models/pipeline/vehicle_attribute_model.zip \
  -o vehicle_attribute_model.zip
```

Модель нужна для первичной проверки типов кузова и как источник начальных весов. Она не заменяет обучение на классах `light`, `medium`, `heavy`, `unknown`.

---

## Базовый детектор номерной зоны

Официальная модель из PP-Vehicle:

```text
https://bj.bcebos.com/v1/paddledet/models/pipeline/ch_PP-OCRv3_det_infer.tar.gz
```

Скачать:

```bash
# скачиваем базовый детектор номерной зоны
cd /opt/vehicle-ai/model-registry/staging

curl -fL \
  https://bj.bcebos.com/v1/paddledet/models/pipeline/ch_PP-OCRv3_det_infer.tar.gz \
  -o ch_pp-ocrv3_det_infer.tar.gz
```

Это временная модель для запуска прототипа. Она не считается готовым российским детектором номера.

---

## Базовый китайский распознаватель номера

Официальная модель из PP-Vehicle:

```text
https://bj.bcebos.com/v1/paddledet/models/pipeline/ch_PP-OCRv3_rec_infer.tar.gz
```

Скачать только для сравнительного теста:

```bash
# скачиваем исходный распознаватель pp-vehicle
cd /opt/vehicle-ai/model-registry/staging

curl -fL \
  https://bj.bcebos.com/v1/paddledet/models/pipeline/ch_PP-OCRv3_rec_infer.tar.gz \
  -o ch_pp-ocrv3_rec_infer.tar.gz
```

Эта модель не должна быть финальной OCR-моделью российских номеров.

---

## Кириллическая OCR-модель PaddleOCR

Официальная карточка модели:

```text
https://huggingface.co/PaddlePaddle/cyrillic_PP-OCRv5_mobile_rec
```

Установить официальный клиент Hugging Face:

```bash
# устанавливаем клиент hugging face
python -m pip install --upgrade huggingface_hub
```

Скачать модель:

```bash
# скачиваем кириллическую модель
cd /opt/vehicle-ai/model-registry/staging

hf download \
  PaddlePaddle/cyrillic_PP-OCRv5_mobile_rec \
  --local-dir cyrillic_pp-ocrv5_mobile_rec
```

Для production её следует дообучить на номерных знаках с ограниченным алфавитом:

```text
0123456789abcehkmoptxy
```

---

# Что пока невозможно скачать готовым

## Классификатор размера

Классы:

```text
light
medium
heavy
unknown
```

Человеку требуется предоставить:

- реальные видео заказчика;
- согласованное определение каждого класса;
- размеченные кропы;
- список спорных случаев;
- отдельные видео для теста.

## Российский детектор номера

Класс:

```text
plate
```

Человеку требуется предоставить:

- кадры с российскими номерами;
- bounding box-разметку;
- дневные и ночные сцены;
- разные углы;
- размытые и частично закрытые номера;
- отдельный закрытый тестовый набор.

---

# Проверка и фиксация SHA-256

После всех загрузок:

```bash
# формируем контрольные суммы
cd /opt/vehicle-ai/model-registry/staging

find . \
  -type f \
  ! -path './PaddleDetection/.git/*' \
  -print0 |
  sort -z |
  xargs -0 sha256sum \
  > sha256sums.txt
```

Сохранить копию:

```bash
# сохраняем контрольные суммы отдельно
sudo cp \
  /opt/vehicle-ai/model-registry/staging/sha256sums.txt \
  /opt/vehicle-ai/model-registry/sha256sums-2026-07-29.txt
```

---

# Перенос моделей в approved

Production-воркеры читают только каталог:

```text
/opt/vehicle-ai/model-registry/approved
```

Копирование выполняется только после появления рядом с моделью:

```text
license.txt
source.json
sha256sums.txt
validation.json
```

Структура:

```text
approved/
  vehicle-detector/0.1.0/
  vehicle-attributes/0.1.0/
  plate-detector-baseline/0.1.0/
  plate-ocr-cyrillic-baseline/0.1.0/
```

---

# Копирование моделей на вторую ноду

```bash
# копируем утверждённые модели на worker-ноду
rsync \
  -aH \
  --delete-delay \
  --checksum \
  /opt/vehicle-ai/model-registry/approved/ \
  vehicle-ai@worker-node:/opt/vehicle-ai/model-registry/approved/
```

После копирования проверить SHA-256.

---

# Установка DeepStream

Официальная документация:

```text
https://docs.nvidia.com/metropolis/deepstream/9.1/text/DS_Overview.html
```

Официальный контейнер NVIDIA NGC:

```text
nvcr.io/nvidia/deepstream:9.1-samples-multiarch
```

На обеих нодах:

```bash
# загружаем официальный deepstream
docker pull \
  nvcr.io/nvidia/deepstream:9.1-samples-multiarch
```

Проверка:

```bash
# проверяем доступ gpu внутри deepstream
docker run \
  --rm \
  --gpus all \
  nvcr.io/nvidia/deepstream:9.1-samples-multiarch \
  nvidia-smi
```

Не использовать тег `latest`.

---

# Центральное хранилище 60 ТБ

Человек должен сообщить агенту:

```yaml
storage:
  type: s3
  endpoint: replace_me
  region: replace_me
  bucket_originals: vehicle-originals
  bucket_derived: vehicle-derived
  bucket_results: vehicle-results
  bucket_models: vehicle-models
```

Обязательные свойства:

- versioning;
- запрет перезаписи оригиналов;
- Object Lock или retention;
- RAID-6 или erasure coding;
- отдельный backup;
- мониторинг дисков;
- желательно 10 Гбит/с между нодами и хранилищем.

---

# Подключение внешней БД

## Текущая временная заглушка

Пока сохранены только веб-адреса:

```text
http://file-ai-srv.rudn.su:8000
http://file-ai.rudn.su
```

Подсказка логина:

```text
admin@localhost.local
```

На момент проверки DNS возвращал `NXDOMAIN`.

Эти адреса не являются строкой подключения к PostgreSQL.

Файл:

```text
/etc/vehicle-ai/external-integration.yaml
```

Содержимое:

```yaml
external_database:
  enabled: false
  mode: stub
  state: dns_nxdomain

  web_url: http://file-ai.rudn.su
  direct_web_url: http://file-ai-srv.rudn.su:8000
  login_hint: admin@localhost.local

  db_type: unknown
  db_host: null
  db_port: null
  db_name: null
  db_user: null
  db_password_file: null
  db_sslmode: null
```

---

## Что получить у администратора БД

Запросить:

```text
тип базы данных
ip или dns сервера
порт базы данных
имя базы
схема
сервисный пользователь
пароль сервисного пользователя
режим tls
корневой сертификат
список разрешённых ip
доступ только на чтение или чтение и запись
описание таблиц
ограничение количества соединений
порядок резервного копирования
```

Нельзя использовать веб-логин `admin@localhost.local` как сервисную учётную запись.

---

## Где хранить пароль БД

```bash
# создаём файл пароля внешней базы
sudo install \
  -m 640 \
  -o root \
  -g vehicle-ai \
  /dev/null \
  /etc/vehicle-ai/secrets/external_db_password
```

Заполнить вручную:

```bash
# открываем секрет для ручного заполнения
sudo nano \
  /etc/vehicle-ai/secrets/external_db_password
```

Агенту передаётся только путь.

---

# Проверка временных веб-адресов

С Windows:

```powershell
# проверяем dns
resolve-dnsname file-ai-srv.rudn.su
resolve-dnsname file-ai.rudn.su

# проверяем порты
test-netconnection file-ai-srv.rudn.su -port 8000
test-netconnection file-ai.rudn.su -port 80

# проверяем http
curl.exe -v --connect-timeout 10 http://file-ai-srv.rudn.su:8000/
curl.exe -v --connect-timeout 10 http://file-ai.rudn.su/
```

---

# Файл входных данных для агента

Создать `operator_inputs.yaml`:

```yaml
project:
  name: vehicle-video-platform
  environment: pilot

main_node:
  hostname: replace_me
  ip_address: replace_me
  gpu_model: replace_me
  gpu_memory_gb: replace_me
  ram_gb: replace_me
  scratch_disk: /srv/vehicle-ai/scratch

worker_node:
  hostname: replace_me
  ip_address: replace_me
  gpu_model: replace_me
  gpu_memory_gb: replace_me
  ram_gb: replace_me
  scratch_disk: /srv/vehicle-ai/scratch

network:
  storage_bandwidth_gbps: replace_me
  private_subnet: replace_me
  public_domain: replace_me

storage:
  type: replace_me
  endpoint: replace_me
  capacity_tb: 60
  versioning_enabled: replace_me
  object_lock_enabled: replace_me
  backup_target: replace_me

models:
  approved_root: /opt/vehicle-ai/model-registry/approved
  checksums_file: /opt/vehicle-ai/model-registry/sha256sums-2026-07-29.txt

external_database:
  enabled: false
  mode: stub
  web_url: http://file-ai.rudn.su
  direct_web_url: http://file-ai-srv.rudn.su:8000
  login_hint: admin@localhost.local
  db_type: unknown
  db_host: null
  db_port: null
  db_name: null
  db_user: null
  db_password_file: null
  db_sslmode: null

security:
  secrets_root: /etc/vehicle-ai/secrets
  public_postgres: false
  public_rabbitmq: false
  gpu_worker_database_access: false
```

---

# Что передать агенту

Передать:

```text
agent_implementation_brief.md
operator_inputs.yaml
operator-evidence/main-node.txt
operator-evidence/worker-node.txt
sha256sums-2026-07-29.txt
описание центрального хранилища
пример реального видео
пример ожидаемого отчёта
описание классов light, medium, heavy, unknown
```

Не передавать:

```text
пароли в сообщениях
root ssh password
административный пароль бд
постоянные ключи s3
закрытые сертификаты
```

---

# Операторский чек-лист

- [ ] обе GPU видны через `nvidia-smi`;
- [ ] Docker видит GPU;
- [ ] DeepStream 9.1 загружен на обе ноды;
- [ ] модели скачаны по указанным ссылкам;
- [ ] SHA-256 сохранён;
- [ ] production-воркеры не используют staging;
- [ ] хранилище 60 ТБ доступно с обеих нод;
- [ ] versioning включён;
- [ ] защита оригиналов определена;
- [ ] backup определён;
- [ ] внешняя БД оставлена в режиме `stub`;
- [ ] у администратора запрошены реквизиты БД;
- [ ] подготовлено тестовое видео;
- [ ] определены классы транспорта;
- [ ] агенту переданы только пути к секретам.
