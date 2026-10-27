# Lecturo

Загружаете видео лекции файлом или ссылкой и получаете расшифровку с таймкодами, главы, конспект, квиз, экспорт в PDF/SRT/VTT и памятку к экзамену по курсу. Всё, что считается на устройстве пользователя, бесплатно.

## Запуск

Нужны Docker и Docker Compose.

```
cp .env.example .env
docker compose up --build
```

Сайт откроется на http://localhost, документация API на http://localhost/api/docs.

По умолчанию провайдеры распознавания, LLM и эмбеддингов работают в режиме `stub`: возвращают тестовые данные, ключи не нужны. Чтобы подключить настоящие, задайте `STT_PROVIDER`, `LLM_PROVIDER`, `EMBEDDINGS_PROVIDER` и ключи в `.env`. Описание всех переменных и инструкции по получению ключей: [docs/env.md](docs/env.md).

Для HTTPS на сервере укажите домен в `SITE_ADDRESS`, Caddy сам получит сертификат. Деплой и автодеплой описаны в [docs/deploy.md](docs/deploy.md).

## Структура

| Путь | Что там |
|---|---|
| `backend/app/api` | эндпоинты FastAPI, по файлу на модуль |
| `backend/app/models` | модели SQLAlchemy |
| `backend/app/schemas` | Pydantic-схемы, из них собирается `backend/openapi.json` |
| `backend/app/providers` | интерфейсы и реализации STT, LLM, эмбеддингов |
| `backend/app/pipeline` | фоновые задачи обработки (arq) |
| `backend/alembic` | миграции |
| `frontend/src/api` | клиент API и типы, сгенерированные из OpenAPI |
| `infra` | Caddy и всё для сервера |

## Разработка

Бэкенд:

```
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
docker compose up -d db redis
DATABASE_URL=postgresql+asyncpg://lecturo:lecturo@localhost:5432/lecturo alembic upgrade head
uvicorn app.main:app --reload
pytest
```

Фронтенд:

```
cd frontend
npm install
npm run dev
```

После изменения схем API обновите контракт и типы:

```
cd backend && python -m app.openapi openapi.json
cd ../frontend && npm run gen:api
```

Новая миграция: `alembic revision --autogenerate -m "что меняем"`. Перед мержем проверьте, что у миграций одна голова (`alembic heads`).

## Лицензия

AGPL-3.0, см. [LICENSE](LICENSE).
