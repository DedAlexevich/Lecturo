# Документация Lecturo

Здесь собраны все документы проекта. Обзор продукта и быстрый запуск — в [README](../README.md).

## Оглавление

| Документ | О чём |
|---|---|
| [env.md](env.md) | все переменные окружения, как получить ключи SpeechKit, DeepSeek, эмбеддингов, Telegram, VK ID, Яндекс ID, ЮKassa |
| [deploy.md](deploy.md) | первая настройка сервера, автодеплой, почта, прокси для YouTube, мониторинг, бэкапы на сервере |
| [data.md](data.md) | где лежат база и файлы лекций, перенос из старых томов Docker |
| [logs.md](logs.md) | логи сервисов, ротация, как смотреть |
| [backups.md](backups.md) | бэкапы базы на локальном стенде: расписание, ручной дамп, восстановление |
| [demo.md](demo.md) | сценарий демо, лекции, тестовый аккаунт, чек-лист прогона |
| [Конвейер обработки](../backend/app/pipeline/README.md) | шаги обработки лекции, повторы запросов к распознаванию, статус и события |
| [Инфраструктура](../infra/README.md) | файлы в `infra/`: скрипты сервера, Caddy, почта, мониторинг, бэкапы |
| [Материалы для README](assets/readme/README.md) | какие скриншоты и видео нужны, как обновить описание репозитория |
| [CONTRIBUTING.md](../CONTRIBUTING.md) | как вести задачи, ветки, коммиты и PR |

## Архитектура

Все сервисы описаны в `docker-compose.yml` и запускаются одной командой.

| Сервис | Что делает |
|---|---|
| `caddy` | принимает HTTP и HTTPS, проксирует фронтенд, `/api` и загрузку файлов, отдаёт видео лекций после проверки доступа |
| `frontend` | собранное React-приложение: сайт, PWA и Telegram Mini App |
| `api` | FastAPI: аккаунты, курсы, лекции, поиск, шаринг, оплата, экспорт |
| `worker` | arq-воркер: скачивание и пережатие видео, распознавание, главы, конспект, квиз, памятка, эмбеддинги |
| `tusd` | приём больших файлов по протоколу tus |
| `db` | PostgreSQL 16 с pgvector: данные и векторы для поиска |
| `redis` | очередь задач и канал событий `lecture-events` |
| `bot`, `bot-redis` | Telegram-бот: `/start`, кнопка Mini App, уведомления о готовых лекциях |
| `db-backup` | ежедневный дамп базы в `data/backups` |

Видео загружается через `tusd` или по ссылке. API создаёт лекцию и ставит задачу в очередь, воркер проходит шаги обработки и пишет их прогресс в `processing_steps`. Распознавание идёт через Yandex SpeechKit (аудио временно кладётся в Object Storage), тексты пишет OpenAI-совместимый LLM (по умолчанию DeepSeek), фрагменты для поиска получают эмбеддинги Yandex и хранятся в pgvector. Поиск гибридный: по смыслу через векторы и по словам через полнотекстовый поиск PostgreSQL. Без ключей все провайдеры работают в режиме `stub`.

В локальном режиме распознавание (Whisper через Transformers.js) и конспект (WebLLM) считаются в браузере, видео на сервер не уходит. Готовый результат можно сохранить в аккаунт через `POST /api/v1/local-results`. Код в `frontend/src/local`.

Схема на Mermaid есть в [README](../README.md#как-устроено).

## Быстрый старт для разработчика

Нужны Docker, Python 3.12 и Node.js 22.

Бэкенд:

```
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
docker compose up -d db redis
DATABASE_URL=postgresql+asyncpg://lecturo:lecturo@localhost:5432/lecturo alembic upgrade head
uvicorn app.main:app --reload
```

Фронтенд:

```
cd frontend
npm install
npm run dev
```

Тесты и проверки, которые запускает CI:

| Где | Команды |
|---|---|
| `backend` | `ruff check .`, `ruff format --check .`, `python ../scripts/check_comments.py . ../scripts`, `pytest` |
| `bot` | `ruff check .`, `ruff format --check .`, `pytest` |
| `frontend` | `npm run lint`, `npm run check:comments`, `npm run test:local`, `npm run build` |
| `frontend`, Mini App | `npm run test:telegram` при запущенном `npx vite --host 127.0.0.1 --port 5186` |
| весь стенд | `docker compose up -d --build --wait`, затем `curl -fsS http://localhost/api/v1/health` |

Миграции:

```
cd backend
alembic revision --autogenerate -m "что меняем"
alembic upgrade head
alembic heads
```

У миграций должна быть одна голова, CI это проверяет. После изменения схем API обновите контракт и типы фронтенда:

```
cd backend && python -m app.openapi openapi.json
cd ../frontend && npm run gen:api
```

`backend/openapi.json` и `frontend/src/api/schema.d.ts` руками не правят, только генерируют.

## Как работать с задачами

1. Каждая задача или баг — это issue по шаблону: [задача](../.github/ISSUE_TEMPLATE/task.md) или [баг](../.github/ISSUE_TEMPLATE/bug.md). Зоны и ответственные — в [#1](https://github.com/DedAlexevich/Lecturo/issues/1).
2. Ветка от свежего `main`: `<номер issue>-<коротко-латиницей>`, например `360-readme-docs`.
3. Коммиты в формате Conventional Commits на русском: `feat(backend): добавить эндпоинт регистрации`.
4. PR в `main` с заголовком в том же формате и `Closes #<номер>` в описании.
5. Ревью и зелёный CI, затем squash-мерж. После мержа в `main` сервер обновляется автоматически, см. [deploy.md](deploy.md#автодеплой).

Подробнее в [CONTRIBUTING.md](../CONTRIBUTING.md).
