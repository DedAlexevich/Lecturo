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

Данные (база, файлы лекций) хранятся в папке `data/` рядом с проектом и переживают `docker compose down -v`. Подробности и перенос из старых томов: [docs/data.md](docs/data.md).

Логи сервисов лежат в `data/logs` с ротацией, описание в [docs/logs.md](docs/logs.md).

Раз в сутки контейнер `db-backup` сохраняет дамп базы в `data/backups` (7 копий). Ручной дамп, восстановление и проверка: [docs/backups.md](docs/backups.md).

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
| `scripts` | вспомогательные скрипты (перенос данных из томов, бэкап и восстановление базы, проверка комментариев) |
| `android` | конфигурация сборки APK (TWA) |

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

## APK для Android

Готовый подписанный APK лежит в `android/lecturo.apk`, его можно сразу ставить на телефон.

APK — это Trusted Web Activity: приложение открывает https://lecturo.ru в Chrome без адресной строки. Проект собирается [Bubblewrap](https://github.com/GoogleChromeLabs/bubblewrap) из `android/twa-manifest.json`, остальное в `android/`, кроме готового APK, генерируется и в репозиторий не попадает.

Нужны Node.js 22. JDK 17 и Android SDK Bubblewrap при первом запуске предложит скачать сам, пути сохраняются в `~/.bubblewrap/config.json`.

Ключ подписи хранится у владельца проекта, в репозитории его нет. Положите его в `android/lecturo-release.keystore` (alias `lecturo`), затем:

```
npm install -g @bubblewrap/cli
cd android
bubblewrap update --skipVersionUpgrade
bubblewrap build --skipPwaValidation
```

Пароли от хранилища и ключа Bubblewrap спросит или возьмёт из `BUBBLEWRAP_KEYSTORE_PASSWORD` и `BUBBLEWRAP_KEY_PASSWORD`. Готовый файл: `android/app-release-signed.apk`, для Google Play — `android/app-release-bundle.aab`.

Новая версия: поднимите `appVersionCode` и `appVersionName` в `twa-manifest.json`, соберите заново и замените `android/lecturo.apk` новым `app-release-signed.apk`.

Сайт подтверждает приложение файлом `frontend/public/.well-known/assetlinks.json`, он отдаётся по https://lecturo.ru/.well-known/assetlinks.json. В нём записан SHA-256 отпечаток сертификата. Если ключ сменился или приложение подписывает Google Play (Play App Signing), возьмите новый отпечаток (`keytool -list -v -keystore android/lecturo-release.keystore -alias lecturo` или Play Console → Целостность приложения) и замените его в `assetlinks.json` и в `fingerprints` в `twa-manifest.json`. Отпечатков может быть несколько. Без совпадающего отпечатка приложение откроется с адресной строкой.

## Лицензия

AGPL-3.0, см. [LICENSE](LICENSE).
