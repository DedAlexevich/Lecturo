# Переменные окружения

Все настройки лежат в файле `.env` в корне репозитория. Он создаётся копированием образца:

```
cp .env.example .env
```

`.env` читают сервисы `api`, `worker` и `bot` (через `env_file` в `docker-compose.yml`). Postgres, Redis и Caddy берут значения из `docker-compose.yml`. Если переменная не задана, используется значение по умолчанию из таблиц ниже. Реальные ключи в репозиторий не коммитим.

## Что нужно для запуска

Локально ничего заполнять не нужно: `cp .env.example .env` и `docker compose up --build`. При `STT_PROVIDER=stub`, `LLM_PROVIDER=stub` и `EMBEDDINGS_PROVIDER=stub` провайдеры возвращают тестовые данные и обходятся без ключей. Без `SMTP_HOST` письма не отправляются, а пишутся в лог сервиса `api` (там же видны ссылки подтверждения почты и сброса пароля). Без `TELEGRAM_BOT_TOKEN` бот не запускается, а вход через Telegram отвечает 503. Без `VK_CLIENT_ID` и `VK_REDIRECT_URI` кнопка входа через VK не показывается, а запросы к VK-эндпоинтам отвечают 503. Так же ведёт себя вход через Яндекс без `YANDEX_OAUTH_CLIENT_ID` и `YANDEX_OAUTH_REDIRECT_URI`.

Для боевого сервера нужно:

- `SITE_ADDRESS` и `PUBLIC_URL` с вашим доменом;
- уникальный `SECRET_KEY` не короче 32 символов (с ключом из `.env.example` сервер не запустится) и свой `POSTGRES_PASSWORD`;
- настоящие провайдеры `STT_PROVIDER`, `LLM_PROVIDER`, `EMBEDDINGS_PROVIDER` и их ключи;
- записи DNS для почты (см. [deploy.md](deploy.md#почта)), иначе письма подтверждения почты и сброса пароля будут попадать в спам;
- Telegram-бот, если нужен вход через Telegram и бот;
- приложение VK ID, если нужен вход через VK;
- приложение на oauth.yandex.ru, если нужен вход через Яндекс;
- ЮKassa, если нужна оплата.

## Основные

| Переменная | Описание | Обязательна | По умолчанию | Где используется |
|---|---|---|---|---|
| `SITE_ADDRESS` | Адрес, на котором Caddy принимает запросы. `:80` значит HTTP на любом хосте, домен (например `lecturo.example`) включает HTTPS с автоматическим сертификатом | на сервере | `:80` | `docker-compose.yml` (caddy), `infra/Caddyfile` |
| `HTTP_PORT` | Порт хоста для HTTP | нет | `80` | `docker-compose.yml` (caddy) |
| `HTTPS_PORT` | Порт хоста для HTTPS | нет | `443` | `docker-compose.yml` (caddy) |
| `PUBLIC_URL` | Публичный адрес сайта, например `https://lecturo.example`. Из него строятся ссылки в письмах, ссылки на шаринг и адрес возврата после оплаты. Бот показывает кнопку «Открыть Lecturo» только если адрес начинается с `https://` | на сервере | `http://localhost` | `backend/app/services/mail.py`, `api/billing.py`, `api/shares.py`, `bot/app/config.py` |
| `SECRET_KEY` | Секрет для подписи токенов входа (JWT), ссылок на экспорт и видео. Длинная случайная строка, например из `openssl rand -hex 32`. Если `PUBLIC_URL` не указывает на localhost или начинается с `https://`, ключ должен быть не короче 32 символов и отличаться от значения по умолчанию и из `.env.example`, иначе `api` и `worker` не стартуют. После смены все пользователи будут разлогинены | на сервере | `dev-secret-change-me-before-production` | `backend/app/core/security.py` |
| `POSTGRES_PASSWORD` | Пароль пользователя `lecturo` в Postgres. Из него же собираются `DATABASE_URL` для `api`, `worker` и `bot` | на сервере | `lecturo` | `docker-compose.yml` (db, api, worker, bot) |
| `FORWARDED_ALLOW_IPS` | С каких адресов `api` принимает `X-Forwarded-For`. По умолчанию это частные диапазоны docker: порт `api` наружу не открыт, до него доходят только контейнеры проекта и сам сервер | нет | `172.16.0.0/12,192.168.0.0/16,10.0.0.0/8` | `docker-compose.yml` (api) |
| `DB_PORT` | Порт Postgres на `127.0.0.1` хоста | нет | `5432` | `docker-compose.yml` (db) |
| `REDIS_PORT` | Порт Redis на `127.0.0.1` хоста | нет | `6379` | `docker-compose.yml` (redis) |
| `DATA_DIR` | Папка на хосте для данных: `postgres`, `storage`, `bot-redis`, `caddy`. Путь абсолютный или относительный к корню репозитория. См. [data.md](data.md) | нет | `./data` | `docker-compose.yml` (db, bot-redis, api, worker, tusd, caddy), `scripts/migrate-volumes.sh` |
| `LOG_MAX_MB` | Размер лог-файла в `data/logs`, при котором он ротируется. См. [logs.md](logs.md) | нет | `10` | `docker-compose.yml`, `backend/app/core/logging.py`, `bot/app/logs.py`, `infra/log-to-file.sh` |
| `LOG_BACKUP_COUNT` | Сколько прежних копий лог-файла хранить | нет | `5` | `docker-compose.yml`, `backend/app/core/logging.py`, `bot/app/logs.py`, `infra/log-to-file.sh` |
| `BACKUP_DIR` | Папка на хосте для бэкапов базы. Путь абсолютный или относительный к корню репозитория. Если не задана, `infra/backup` использует `./backups`, а контейнер `db-backup` и `scripts/backup-db.sh` с `scripts/restore-db.sh` берут `${DATA_DIR}/backups`. См. [backups.md](backups.md) и [deploy.md](deploy.md#бэкапы-базы) | нет | `./backups` на сервере, `./data/backups` локально | `docker-compose.yml` (db-backup), `infra/backup`, `scripts` |
| `BACKUP_KEEP` | Сколько последних бэкапов хранить, целое число от 1 | нет | `7` | `docker-compose.yml` (db-backup), `infra/backup` |
| `BACKUP_INTERVAL_HOURS` | Как часто контейнер `db-backup` делает дамп, в часах. Расписание сохраняется между перезапусками: если свежий дамп уже есть, следующий делается через оставшееся время | нет | `24` | `docker-compose.yml` (db-backup), `infra/backup/schedule.sh` |
| `BACKUP_DB_SERVICE` | Сервис compose с Postgres, к которому подключаются скрипты бэкапа | нет | `db` | `infra/backup` |
| `BACKUP_DB_CONTAINER` | Имя контейнера с Postgres. Если задано, скрипты бэкапа идут через `docker exec` в него, а не через compose | нет | пусто | `infra/backup` |
| `BACKUP_CHECK_CONTAINER` | Имя временного контейнера Postgres, в котором `check.sh` проверяет восстановление бэкапа | нет | `lecturo-backup-check` | `infra/backup/check.sh` |
| `BACKUP_AGE_RECIPIENT` | Публичный ключ age владельца (`age1...`). Если задан, бэкап на сервере вместе с ключом DKIM шифруется в `lecturo-<дата>-<время>.tar.age`, иначе остаётся незашифрованный `.dump`. См. [deploy.md](deploy.md#ключ-шифрования) | на сервере | пусто | `infra/backup` |
| `BACKUP_AGE_IDENTITY` | Путь к приватному ключу age. Задаётся только на время запуска `restore.sh` для `.tar.age`, в `.env` не хранится | для восстановления | пусто | `infra/backup/restore.sh` |
| `BACKUP_S3_BUCKET` | Бакет Yandex Object Storage для копии бэкапов вне сервера. Если не задан вместе с ключами, выгрузка пропускается. См. [deploy.md](deploy.md#копия-в-yandex-object-storage) | на сервере | пусто | `infra/backup/common.sh` |
| `BACKUP_S3_ACCESS_KEY_ID` | Идентификатор статического ключа сервисного аккаунта с ролью `storage.uploader` на этот бакет | на сервере | пусто | `infra/backup/common.sh` |
| `BACKUP_S3_SECRET_ACCESS_KEY` | Секрет этого ключа | на сервере | пусто | `infra/backup/common.sh` |
| `BACKUP_S3_ENDPOINT` | Адрес S3 API | нет | `https://storage.yandexcloud.net` | `infra/backup/common.sh` |
| `BACKUP_S3_REGION` | Регион для подписи запросов | нет | `ru-central1` | `infra/backup/common.sh` |

`DATABASE_URL` и `REDIS_URL` в `.env` писать не нужно: `docker-compose.yml` задаёт их сам. Остальные настройки backend, которых нет в `.env.example` (`ACCESS_TOKEN_TTL_MINUTES`, `STORAGE_DIR`, `YOOKASSA_API_URL`, `LOCAL_*`, `AUTH_MAIL_*`, `ACCOUNT_DELETE_*`), имеют значения по умолчанию в `backend/app/core/config.py`, менять их обычно не требуется.

## Распознавание речи (STT)

`STT_PROVIDER` принимает `stub` или `yandex`. Другое значение приведёт к ошибке «Неизвестный STT_PROVIDER». Если провайдер выбран, но не хватает обязательных значений, при его создании будет ошибка «Не заданы настройки ...» со списком недостающих переменных.

| Переменная | Описание | Обязательна | По умолчанию | Где используется |
|---|---|---|---|---|
| `STT_PROVIDER` | `stub` или `yandex` | нет | `stub` | `backend/app/providers/__init__.py` |
| `YANDEX_SPEECHKIT_API_KEY` | API-ключ сервисного аккаунта для SpeechKit | при `yandex` | пусто | `backend/app/providers/yandex.py` |
| `YANDEX_FOLDER_ID` | Идентификатор каталога Yandex Cloud, передаётся в запрос распознавания как `folderId` | рекомендуется при `yandex`, код работает и без него | пусто | `backend/app/providers/yandex.py` |
| `YANDEX_STORAGE_BUCKET` | Имя бакета Object Storage, куда на время распознавания загружается аудио | при `yandex` | пусто | `backend/app/providers/yandex.py` |
| `YANDEX_STORAGE_ACCESS_KEY` | Идентификатор статического ключа доступа | при `yandex` | пусто | `backend/app/providers/yandex.py` |
| `YANDEX_STORAGE_SECRET_KEY` | Секретная часть статического ключа доступа | при `yandex` | пусто | `backend/app/providers/yandex.py` |
| `STT_RETRY_ATTEMPTS` | Сколько раз всего пробовать запрос к SpeechKit при временной ошибке (429, 500, 502, 503, 504, код 13, таймаут или обрыв соединения). `1` отключает повторы | нет | `5` | `backend/app/providers/retry.py` |
| `STT_RETRY_BASE_SECONDS` | Пауза перед первым повтором, секунды | нет | `2` | `backend/app/providers/retry.py` |
| `STT_RETRY_FACTOR` | Во сколько раз растёт пауза после каждой неудачи. При значениях по умолчанию паузы около 2, 6, 18 и 54 секунд, к каждой добавляется случайный разброс до 20% | нет | `3` | `backend/app/providers/retry.py` |
| `STT_RETRY_MAX_SECONDS` | Верхняя граница одной паузы, секунды | нет | `60` | `backend/app/providers/retry.py` |
| `STT_POLL_SECONDS` | Как часто опрашивать операцию распознавания SpeechKit, секунды | нет | `3` | `backend/app/providers/yandex.py` |
| `STT_EXPECTED_RATIO` | Ожидаемая длительность распознавания как доля длительности записи. По ней считаются прогресс шага «Распознавание речи» и оценка оставшегося времени. Не больше 95% до ответа провайдера. Для длинных записей считается на одну часть | нет | `0.3` | `backend/app/providers/yandex.py, backend/app/pipeline/estimate.py` |
| `STT_EXPECTED_MIN_SECONDS` | Нижняя граница ожидаемой длительности распознавания, секунды | нет | `45` | `backend/app/pipeline/estimate.py`, `backend/app/providers/yandex.py` |
| `STT_CHUNK_THRESHOLD_SECONDS` | Записи длиннее этого порога режутся на части и распознаются параллельно, секунды. Более короткие уходят в SpeechKit одним запросом | нет | `720` | `backend/app/providers/yandex.py`, `backend/app/pipeline/estimate.py` |
| `STT_CHUNK_TARGET_SECONDS` | Целевая длина одной части, секунды. Границы ищутся в паузах в пределах 30 секунд от целевой точки, если пауз нет, режется ровно по цели | нет | `420` | `backend/app/providers/chunks.py` |
| `STT_PARALLEL_PARTS` | Сколько частей одной лекции распознаются одновременно. Учитывайте лимит SpeechKit на число одновременных операций в облаке | нет | `3` | `backend/app/providers/yandex.py`, `backend/app/pipeline/estimate.py` |
| `ETA_DOWNLOAD_RATIO` | Ожидаемая длительность скачивания как доля длительности записи, для оценки оставшегося времени | нет | `0.1` | `backend/app/pipeline/estimate.py` |
| `ETA_AUDIO_RATIO` | То же для извлечения звука | нет | `0.01` | `backend/app/pipeline/estimate.py` |
| `ETA_SUMMARIZE_RATIO` | То же для шага «Главы и конспект» | нет | `0.05` | `backend/app/pipeline/estimate.py` |
| `ETA_EMBED_RATIO` | То же для подготовки к поиску | нет | `0.01` | `backend/app/pipeline/estimate.py` |

### Yandex Cloud: SpeechKit и Object Storage

Названия разделов и кнопок в консоли могут меняться, ориентируйтесь на смысл.

1. Зарегистрируйтесь в [консоли Yandex Cloud](https://console.yandex.cloud) и создайте платёжный аккаунт: SpeechKit и Object Storage платные.
2. Создайте каталог или выберите существующий. Его идентификатор виден на странице каталога, это `YANDEX_FOLDER_ID`.
3. В каталоге создайте сервисный аккаунт и назначьте ему роли `ai.speechkit-stt.user` (распознавание речи) и `storage.editor` (запись и удаление объектов в бакетах каталога).
4. В сервисном аккаунте создайте API-ключ. Если консоль предлагает область действия, выберите распознавание речи SpeechKit. Секретная часть показывается один раз, её значение идёт в `YANDEX_SPEECHKIT_API_KEY`.
5. В том же сервисном аккаунте создайте статический ключ доступа. Идентификатор ключа идёт в `YANDEX_STORAGE_ACCESS_KEY`, секретный ключ (тоже показывается один раз) в `YANDEX_STORAGE_SECRET_KEY`.
6. В каталоге создайте бакет Object Storage. Имя бакета уникально для всего облака, оно идёт в `YANDEX_STORAGE_BUCKET`. Публичный доступ включать не нужно: бэкенд загружает файл подписанным запросом, а после распознавания удаляет его из бакета.
7. В `.env` задайте `STT_PROVIDER=yandex` и примените настройки: `docker compose up -d`.

Бэкенд обращается к `storage.yandexcloud.net` и к API распознавания `transcribe.api.cloud.yandex.net`.

## LLM и эмбеддинги

Провайдер `openai` работает с любым сервисом, совместимым с OpenAI API. Бэкенд отправляет запросы на `<BASE_URL>/chat/completions` и `<BASE_URL>/embeddings` с заголовком `Authorization: Bearer <KEY>`. Допустимые значения провайдера LLM: `stub` и `openai`, провайдера эмбеддингов: `stub`, `openai` и `yandex` (отдельный API Yandex Foundation Models, см. ниже).

| Переменная | Описание | Обязательна | По умолчанию | Где используется |
|---|---|---|---|---|
| `LLM_PROVIDER` | `stub` или `openai` | нет | `stub` | `backend/app/providers/__init__.py` |
| `LLM_BASE_URL` | Базовый адрес API | при `openai` | `https://api.deepseek.com` | `backend/app/providers/openai_compat.py` |
| `LLM_API_KEY` | Ключ API | при `openai` | пусто | `backend/app/providers/openai_compat.py` |
| `LLM_MODEL` | Название модели | при `openai` | `deepseek-chat` | `backend/app/providers/openai_compat.py` |
| `EMBEDDINGS_PROVIDER` | `stub`, `openai` или `yandex` | нет | `stub` | `backend/app/providers/__init__.py` |
| `EMBEDDINGS_BASE_URL` | Базовый адрес API эмбеддингов | при `openai` | пусто | `backend/app/providers/openai_compat.py` |
| `EMBEDDINGS_API_KEY` | Ключ API эмбеддингов | при `openai` | пусто | `backend/app/providers/openai_compat.py` |
| `EMBEDDINGS_MODEL` | Название модели эмбеддингов | при `openai` | пусто | `backend/app/providers/openai_compat.py` |
| `YANDEX_EMBEDDINGS_API_KEY` | API-ключ сервисного аккаунта для эмбеддингов Yandex. Если пуст, берётся `YANDEX_SPEECHKIT_API_KEY` | при `yandex`, если нет `YANDEX_SPEECHKIT_API_KEY` | пусто | `backend/app/providers/yandex.py` |
| `YANDEX_EMBEDDINGS_FOLDER_ID` | Идентификатор каталога для эмбеддингов Yandex. Если пуст, берётся `YANDEX_FOLDER_ID` | при `yandex`, если нет `YANDEX_FOLDER_ID` | пусто | `backend/app/providers/yandex.py` |
| `YANDEX_EMBEDDINGS_BASE_URL` | Адрес API Yandex Foundation Models | нет | `https://ai.api.cloud.yandex.net` | `backend/app/providers/yandex.py` |

### LLM: DeepSeek или другой OpenAI-совместимый сервис

DeepSeek:

1. Зарегистрируйтесь на [platform.deepseek.com](https://platform.deepseek.com) и пополните баланс.
2. В разделе с API-ключами создайте ключ и впишите его в `LLM_API_KEY`.
3. Оставьте `LLM_BASE_URL=https://api.deepseek.com` и `LLM_MODEL=deepseek-chat`, задайте `LLM_PROVIDER=openai`.

Другой сервис (OpenAI, OpenRouter, свой сервер с OpenAI-совместимым API): получите у него ключ, в `LLM_BASE_URL` укажите базовый адрес, в `LLM_MODEL` название модели из его документации. Ключ не должен быть пустым: если сервер его не проверяет, впишите любую непустую строку. Адрес указывается без `/chat/completions`, этот путь бэкенд добавляет сам (у части сервисов базовый адрес оканчивается на `/v1`).

### Эмбеддинги

Размерность вектора в базе фиксирована: 256 (`EMBEDDING_DIM` в `backend/app/models/base.py`), столько отдают модели Yandex. Для `openai` модель должна отдавать векторы такой длины или позволять её задать (например, параметр `dimensions`), иначе запуск воркера и индексация завершатся ошибкой о размерности.

#### Yandex Foundation Models (`EMBEDDINGS_PROVIDER=yandex`)

Бэкенд отправляет по одному тексту в запросе `POST <YANDEX_EMBEDDINGS_BASE_URL>/foundationModels/v1/textEmbedding` с заголовками `Authorization: Api-Key <ключ>` и `x-folder-id: <каталог>`. Фрагменты лекций при индексации считаются моделью `text-search-doc`, поисковые запросы моделью `text-search-query`. Одновременно идёт не больше 4 запросов, при ответах 429 и 5xx запрос повторяется с растущей задержкой.

1. В [консоли Yandex Cloud](https://console.yandex.cloud) выберите каталог. Его идентификатор это `YANDEX_FOLDER_ID` (или `YANDEX_EMBEDDINGS_FOLDER_ID`).
2. Сервисному аккаунту выдайте в этом каталоге роль `ai.languageModels.user` (или выше). Без неё запросы получат ответ 403.
3. Создайте API-ключ сервисного аккаунта. Если консоль предлагает область действия, выберите ту, что разрешает обращение к моделям Foundation Models. Ключ от SpeechKit можно использовать, если у него есть и эта роль, и подходящая область. Иначе создайте отдельный ключ и впишите его в `YANDEX_EMBEDDINGS_API_KEY`.
4. Задайте `EMBEDDINGS_PROVIDER=yandex` и примените настройки: `docker compose up -d`. При запуске воркер делает один тестовый запрос: при неверном ключе или отсутствии роли в логе будет ответ API (401 или 403), и воркер не стартует.

#### Другой сервис (`EMBEDDINGS_PROVIDER=openai`)

1. Выберите сервис с OpenAI-совместимым методом эмбеддингов (`<EMBEDDINGS_BASE_URL>/embeddings`). Подойдёт OpenAI или свой сервер. Доступность метода у конкретного сервиса проверьте в его документации.
2. Получите у сервиса ключ и впишите его в `EMBEDDINGS_API_KEY`, адрес в `EMBEDDINGS_BASE_URL`, модель в `EMBEDDINGS_MODEL`.
3. Задайте `EMBEDDINGS_PROVIDER=openai` и примените настройки: `docker compose up -d`.

#### Смена размерности и переиндексация

Миграция `0006` меняет колонку `search_chunks.embedding` с `vector(1024)` на `vector(256)`, пересоздаёт векторный индекс и обнуляет существующие векторы. Пока вектора пусты, поиск идёт только по тексту. Чтобы пересчитать их после миграции и смены провайдера:

```
docker compose exec worker python -m app.pipeline.reindex
```

Поиску нужен pgvector 0.8 или новее (итеративный обход HNSW-индекса с фильтром по владельцу). Если образ `pgvector/pgvector:pg16` на сервере старый, обновите его: `docker compose pull db && docker compose up -d db`.

Команда сначала добавляет в индекс главы и разделы конспекта у лекций, где их ещё нет (лекции, обработанные до глобального поиска), затем берёт фрагменты без вектора, считает их текущим провайдером и выводит оба числа. Её можно запускать повторно: уже добавленные и посчитанные фрагменты она не трогает. Лекции, которые обрабатываются заново, получают фрагменты и вектора на шаге `embed`, в том числе после пересоздания глав и конспекта.

## Почта (SMTP)

Почта нужна для писем подтверждения адреса и сброса пароля. Если `SMTP_HOST` пуст, письма не уходят, а пишутся в лог `api`.

На сервере письма по умолчанию отправляет свой SMTP, сервис `mail` из `infra/compose.prod.yml` (см. [deploy.md](deploy.md#почта)). Если `SMTP_HOST`, `SMTP_PORT` и `SMTP_FROM` в `.env` пусты, compose подставляет `mail`, `587` и `Lecturo <noreply@<домен>>`. Заполняйте их, только если нужен внешний SMTP, например Яндекс или Gmail, тогда `mail` просто не используется. Для внешнего SMTP на сервере `SMTP_FROM` обязателен: если его не задать, письма пойдут от `noreply@<домен>` и провайдер их отклонит.

| Переменная | Описание | Обязательна | По умолчанию | Где используется |
|---|---|---|---|---|
| `SMTP_HOST` | Адрес SMTP-сервера | нет | пусто, на сервере `mail` | `backend/app/services/mail.py`, `infra/compose.prod.yml` |
| `SMTP_PORT` | Порт. `465` включает SSL сразу при подключении, любой другой порт работает через STARTTLS (обычно `587`) | нет | `587` | `backend/app/services/mail.py` |
| `SMTP_USER` | Логин. Если пуст, авторизация не выполняется | обычно да | пусто | `backend/app/services/mail.py` |
| `SMTP_PASSWORD` | Пароль. Для Яндекса и Gmail нужен пароль приложения | обычно да | пусто | `backend/app/services/mail.py` |
| `SMTP_FROM` | Адрес в поле «От». Локально при пустом значении берётся `SMTP_USER`, на сервере подставляется `noreply@<домен>`, поэтому для внешнего SMTP там его нужно заполнить | на сервере с внешним SMTP | пусто, на сервере `Lecturo <noreply@<домен>>` | `backend/app/services/mail.py`, `infra/compose.prod.yml` |
| `COMPLAINTS_EMAIL` | Адрес, на который приходит письмо о каждой новой жалобе на публичную ссылку. Пусто: жалоба только сохраняется в базе и пишется в лог | нет | пусто | `backend/app/api/shares.py` |
| `MAIL_DOMAIN` | Домен, от имени которого `mail` отправляет и подписывает письма. Только один домен без схемы и порта, например `lecturo.example`. Если в `SITE_ADDRESS` несколько адресов или схема, задайте `MAIL_DOMAIN` явно, иначе `mail` не запустится | нет | значение `SITE_ADDRESS` | `infra/compose.prod.yml`, `infra/mail` |

Яндекс Почта:

1. В настройках почты Яндекса разрешите доступ с почтовых клиентов по протоколу IMAP, иначе вход по SMTP может не заработать.
2. В [Яндекс ID](https://id.yandex.ru) в разделе безопасности создайте пароль приложения для почты. Яндекс может потребовать включить двухфакторную защиту.
3. Заполните: `SMTP_HOST=smtp.yandex.ru`, `SMTP_PORT=465`, `SMTP_USER` полный адрес ящика, `SMTP_PASSWORD` пароль приложения, `SMTP_FROM` тот же адрес.

Gmail:

1. В аккаунте Google включите двухэтапную аутентификацию.
2. На странице [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) создайте пароль приложения. Он состоит из 16 символов, в `.env` пробелы уберите.
3. Заполните: `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587` (STARTTLS) или `465` (SSL), `SMTP_USER` и `SMTP_FROM` адрес Gmail, `SMTP_PASSWORD` пароль приложения.

Для других провайдеров возьмите параметры SMTP из их документации. Порт `465` идёт через SSL, все остальные через STARTTLS. Если письмо не отправилось, в логе `api` будет запись «Не удалось отправить письмо».

## Telegram

| Переменная | Описание | Обязательна | По умолчанию | Где используется |
|---|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Токен бота от BotFather | для бота и входа через Telegram | пусто | `bot/app/config.py`, `backend/app/services/telegram_auth.py` |
| `TELEGRAM_BOT_USERNAME` | Имя бота без `@`. Передаётся в сборку фронтенда как `VITE_TELEGRAM_BOT_USERNAME` | для кнопки входа | пусто | `backend/app/core/config.py` |
| `VITE_TELEGRAM_BOT_USERNAME` | Имя бота без `@` для кнопки Login Widget на странице входа. Читается при сборке фронтенда; в Docker-сборке берётся из `TELEGRAM_BOT_USERNAME` | для кнопки входа | не задана | `frontend/src/pages/auth/TelegramButton.tsx` |
| `TELEGRAM_API_IP` | IP, на который в проде указывает `api.telegram.org` для бота и алертов. Нужен, потому что с сервера основной адрес Telegram недоступен. Если бот перестал отвечать с таймаутами, проверьте адрес: `curl --resolve api.telegram.org:443:<ip> https://api.telegram.org/` | только на сервере | `149.154.167.220` | `infra/compose.prod.yml`, `infra/notify.sh` |
| `YOUTUBE_PROXY` | Прокси для скачивания аудио с YouTube, например `socks5h://ytproxy:<пароль>@<ip>:1080`. С сервера в РФ YouTube недоступен, поэтому ссылки YouTube качаются через зарубежный сервер, остальные источники идут напрямую. Если пусто, YouTube качается напрямую. Как поднять прокси, описано в [deploy.md](deploy.md#прокси-для-youtube) | только на сервере | пусто | `backend/app/pipeline/download.py` |
| `ALERT_TELEGRAM_CHAT_ID` | Числовой id чата владельца, куда бот присылает сообщение, если сайт перестал отвечать, бэкап упал или устарел. Подробнее в [deploy.md](deploy.md#мониторинг-и-логи) | для алертов на сервере | пусто | `infra/notify.sh` |

Если имя бота не задано при сборке, кнопка входа через Telegram не показывается. После изменения `TELEGRAM_BOT_USERNAME` фронтенд нужно пересобрать: `docker compose up -d --build frontend caddy`.

Получение токена и настройка бота:

1. В Telegram откройте [@BotFather](https://t.me/BotFather) и отправьте `/newbot`.
2. Задайте имя и username бота (оканчивается на `bot`). BotFather пришлёт токен, его значение идёт в `TELEGRAM_BOT_TOKEN`. Username без `@` впишите в `TELEGRAM_BOT_USERNAME`.
3. Для Login Widget отправьте BotFather `/setdomain`, выберите бота и укажите домен сайта, например `lecturo.example`. Виджет работает только на этом домене, на `localhost` проверить вход не получится.
4. Примените настройки: `docker compose up -d`. Бот отвечает на `/start`, сохраняет `chat_id` пользователя и, если `PUBLIC_URL` начинается с `https://`, показывает кнопку открытия приложения.

Бэкенд проверяет подпись данных входа по токену бота и принимает данные не старше суток. Токен никому не передавайте. Если он утёк, выпустите новый через BotFather.

## VK ID

| Переменная | Описание | Обязательна | По умолчанию | Где используется |
|---|---|---|---|---|
| `VK_CLIENT_ID` | ID приложения из кабинета VK ID | для входа через VK | пусто | `backend/app/core/config.py`, `backend/app/services/vk_auth.py` |
| `VK_REDIRECT_URI` | Адрес, на который VK возвращает пользователя после входа: `<PUBLIC_URL>/auth/vk`, например `https://lecturo.example/auth/vk`. Должен совпадать с Redirect URL приложения символ в символ | для входа через VK | пусто | `backend/app/core/config.py`, `backend/app/services/vk_auth.py` |

Если одна из двух переменных пуста, вход и привязка VK отключены: страница входа и настройки аккаунта не показывают кнопки, а `POST /api/v1/auth/vk/start` отвечает 503. Фронтенд узнаёт о настройке у бэкенда (`GET /api/v1/auth/providers`), поэтому пересобирать его после изменения переменных не нужно, достаточно перезапустить `api`: `docker compose up -d api`.

Используется авторизационный код с PKCE: бэкенд сам создаёт `state` и `code_verifier`, хранит их в Redis 10 минут и обменивает код на токен запросом `POST https://id.vk.com/oauth2/auth`. Секрет приложения для этого обмена не нужен, поэтому отдельной переменной для него нет.

Как получить ID приложения:

1. Откройте [id.vk.com/about/business/go](https://id.vk.com/about/business/go) и войдите под аккаунтом VK, которому будет принадлежать приложение.
2. Создайте приложение с платформой «Web».
3. В настройках приложения укажите базовый домен сайта и доверенный Redirect URL, равный значению `VK_REDIRECT_URI`. Названия пунктов в кабинете могут отличаться, сверяйтесь с [документацией VK ID](https://id.vk.com/about/business/go/docs).
4. Скопируйте ID приложения в `VK_CLIENT_ID`, а `VK_REDIRECT_URI` впишите в `.env`.
5. Примените настройки: `docker compose up -d api`.

Новому пользователю при первом входе через VK нужно принять пользовательское соглашение и согласие на обработку персональных данных, как и при входе через Telegram. Без обоих согласий аккаунт не создаётся.

## Яндекс ID (вход через Яндекс)

Это OAuth-приложение на oauth.yandex.ru, оно не связано с `YANDEX_SPEECHKIT_API_KEY`, `YANDEX_FOLDER_ID` и ключами Object Storage из раздела про распознавание речи: там Yandex Cloud, здесь Яндекс ID.

| Переменная | Описание | Обязательна | По умолчанию | Где используется |
|---|---|---|---|---|
| `YANDEX_OAUTH_CLIENT_ID` | ID приложения (ClientID) из кабинета oauth.yandex.ru | для входа через Яндекс | пусто | `backend/app/core/config.py`, `backend/app/services/yandex_auth.py` |
| `YANDEX_OAUTH_REDIRECT_URI` | Адрес, на который Яндекс возвращает пользователя после входа: `<PUBLIC_URL>/auth/yandex`, например `https://lecturo.example/auth/yandex`. Должен совпадать с Callback URI приложения символ в символ | для входа через Яндекс | пусто | `backend/app/core/config.py`, `backend/app/services/yandex_auth.py` |
| `YANDEX_OAUTH_CLIENT_SECRET` | Пароль приложения (Client secret). Если задан, отправляется при обмене кода на токен вместе с PKCE | нет | пусто | `backend/app/core/config.py`, `backend/app/services/yandex_auth.py` |

Если `YANDEX_OAUTH_CLIENT_ID` или `YANDEX_OAUTH_REDIRECT_URI` пуста, вход и привязка Яндекса отключены: страница входа и настройки аккаунта не показывают кнопки, а `POST /api/v1/auth/yandex/start` отвечает 503. Фронтенд узнаёт о настройке у бэкенда (`GET /api/v1/auth/providers`), поэтому пересобирать его после изменения переменных не нужно, достаточно перезапустить `api`: `docker compose up -d api`.

Используется авторизационный код с PKCE: бэкенд сам создаёт `state` и `code_verifier`, хранит их в Redis 10 минут, отправляет пользователя на `https://oauth.yandex.ru/authorize`, обменивает код на токен запросом `POST https://oauth.yandex.ru/token` и читает профиль с `https://login.yandex.ru/info`. Секрет приложения для обмена с PKCE не нужен, но если вы его укажете, он будет отправлен.

Как получить ID и секрет приложения:

1. Откройте [oauth.yandex.ru](https://oauth.yandex.ru) и войдите под аккаунтом Яндекса, которому будет принадлежать приложение.
2. Создайте новое приложение, платформа «Веб-сервисы».
3. В поле Callback URI укажите значение `YANDEX_OAUTH_REDIRECT_URI`.
4. В доступах приложения выберите право на доступ к логину, имени и фамилии пользователя (право `login:info`). Названия пунктов в кабинете могут отличаться, сверяйтесь с [документацией Яндекс ID](https://yandex.ru/dev/id/doc/ru/).
5. Сохраните приложение. На его странице будут ID (ClientID) и пароль (Client secret). ID впишите в `YANDEX_OAUTH_CLIENT_ID`, а `YANDEX_OAUTH_REDIRECT_URI` в `.env`. Пароль нужен только если хотите передавать его при обмене кода, тогда он идёт в `YANDEX_OAUTH_CLIENT_SECRET`. Пароль никому не передавайте.
6. Примените настройки: `docker compose up -d api`.

Новому пользователю при первом входе через Яндекс нужно принять пользовательское соглашение и согласие на обработку персональных данных, как и при входе через Telegram и VK. Без обоих согласий аккаунт не создаётся.

Поток проверен только на замоканных ответах Яндекса.

## Оплата (ЮKassa)

| Переменная | Описание | Обязательна | По умолчанию | Где используется |
|---|---|---|---|---|
| `YOOKASSA_SHOP_ID` | Идентификатор магазина | для оплаты | пусто | `backend/app/services/yookassa.py` |
| `YOOKASSA_SECRET_KEY` | Секретный ключ магазина | для оплаты | пусто | `backend/app/services/yookassa.py` |
| `YOOKASSA_RECEIPT` | `true`: добавлять в платёж данные чека. Тогда у пользователя должен быть email, иначе платёж не создаётся | нет | `false` | `backend/app/services/yookassa.py` |

Без `YOOKASSA_SHOP_ID` и `YOOKASSA_SECRET_KEY` оплата недоступна.

Тестовый магазин:

1. Зарегистрируйтесь в [личном кабинете ЮKassa](https://yookassa.ru) и создайте тестовый магазин.
2. В настройках магазина найдите идентификатор магазина и впишите его в `YOOKASSA_SHOP_ID`.
3. В разделе с ключами API выпустите секретный ключ и впишите его в `YOOKASSA_SECRET_KEY`. Ключ показывается один раз.
4. В настройках HTTP-уведомлений укажите адрес `https://<домен>/api/v1/billing/webhook` и события `payment.succeeded`, `payment.canceled` и `refund.succeeded`. По `refund.succeeded` при полном возврате отзывается подписка или пакет часов. Адрес должен быть доступен из интернета, поэтому на локальной машине для проверки уведомлений нужен туннель.
5. Для оплаты в тестовом магазине используйте тестовые карты из документации ЮKassa: реальные деньги не списываются.
6. Для боевого магазина пройдите подключение в ЮKassa и замените идентификатор и ключ на боевые. Если нужен чек, включите `YOOKASSA_RECEIPT=true`.

Адрес API (`YOOKASSA_API_URL`, по умолчанию `https://api.yookassa.ru/v3`) менять не нужно.

## Тарифы и лимиты

Все значения необязательны, значения по умолчанию совпадают с `.env.example`.

| Переменная | Описание | По умолчанию | Где используется |
|---|---|---|---|
| `FREE_WEEKLY_SECONDS` | Недельный лимит обработки на бесплатном тарифе, секунды (2 часа) | `7200` | `backend/app/services/quota.py` |
| `SUBSCRIPTION_WEEKLY_SECONDS` | Недельный лимит по подписке, секунды (10 часов) | `36000` | `backend/app/services/quota.py` |
| `SUBSCRIPTION_PRICE_RUB` | Цена подписки, рубли | `299` | `backend/app/services/quota.py` |
| `SUBSCRIPTION_DAYS` | Срок подписки, дни | `30` | `backend/app/services/quota.py`, `backend/app/services/yookassa.py` |
| `HOUR_PACKAGES` | Пакеты часов в формате JSON: `{"часы": цена в рублях}` | `{"5": 199, "10": 349}` | `backend/app/services/quota.py` |
| `FREE_VIDEO_RETENTION_DAYS` | Сколько дней хранится видео у бесплатных пользователей | `3` | `backend/app/services/quota.py`, `backend/app/pipeline/media.py` |
| `SUBSCRIPTION_VIDEO_RETENTION_DAYS` | Сколько дней хранится видео у подписчиков | `30` | `backend/app/services/quota.py` |
| `LOCAL_EMBEDDINGS_WEEKLY_SECONDS` | Недельный лимит секунд для результатов, посчитанных на устройстве пользователя (10 часов) | `36000` | `backend/app/api/local_results.py` |

## Администраторы

| Переменная | Описание | По умолчанию | Где используется |
|---|---|---|---|
| `INITIAL_ADMINS` | Почты или Telegram id через запятую. При старте api, если в базе ещё нет ни одного администратора, найденные пользователи получают права администратора. Если администратор уже есть, переменная ничего не меняет. Подробнее в [deploy.md](deploy.md#первый-администратор) | пусто | `backend/app/main.py`, `backend/app/services/admin.py` |

## Проверка

После изменения `.env` примените настройки: `docker compose up -d`. Ошибки конфигурации (неизвестный провайдер, не хватает ключей) видны в логах: `docker compose logs api worker bot`.
