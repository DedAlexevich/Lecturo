<div align="center">

<img src="frontend/public/favicon.svg" alt="Lecturo" width="96" height="96">

<h1>Lecturo</h1>

<p>Превращает видео лекций в расшифровку с таймкодами, главы, конспект, квиз и памятку к экзамену.</p>

<p>
<a href="https://lecturo.ru"><img alt="Сайт" src="https://img.shields.io/badge/%D0%A1%D0%B0%D0%B9%D1%82-lecturo.ru-14161a?style=for-the-badge"></a>
<a href="docs/README.md"><img alt="Документация" src="https://img.shields.io/badge/%D0%94%D0%BE%D0%BA%D1%83%D0%BC%D0%B5%D0%BD%D1%82%D0%B0%D1%86%D0%B8%D1%8F-14161a?style=for-the-badge"></a>
<a href="docs/deploy.md"><img alt="Деплой" src="https://img.shields.io/badge/%D0%94%D0%B5%D0%BF%D0%BB%D0%BE%D0%B9-14161a?style=for-the-badge"></a>
<a href="https://t.me/lecturo_notes_bot"><img alt="Telegram-бот" src="https://img.shields.io/badge/Telegram--%D0%B1%D0%BE%D1%82-6ea5f2?style=for-the-badge&logo=telegram&logoColor=white"></a>
<a href="https://github.com/DedAlexevich/Lecturo/issues/new/choose"><img alt="Сообщить о проблеме" src="https://img.shields.io/badge/%D0%A1%D0%BE%D0%BE%D0%B1%D1%89%D0%B8%D1%82%D1%8C%20%D0%BE%20%D0%BF%D1%80%D0%BE%D0%B1%D0%BB%D0%B5%D0%BC%D0%B5-14161a?style=for-the-badge"></a>
</p>

<p>
<a href="https://github.com/DedAlexevich/Lecturo/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/DedAlexevich/Lecturo/actions/workflows/ci.yml/badge.svg?branch=main"></a>
<a href="LICENSE"><img alt="Лицензия AGPL-3.0" src="https://img.shields.io/badge/license-AGPL--3.0-blue"></a>
<img alt="Python 3.12" src="https://img.shields.io/badge/Python-3.12-3776ab?logo=python&logoColor=white">
<img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white">
<img alt="React 18" src="https://img.shields.io/badge/React-18-61dafb?logo=react&logoColor=black">
<img alt="TypeScript" src="https://img.shields.io/badge/TypeScript-3178c6?logo=typescript&logoColor=white">
<img alt="PostgreSQL и pgvector" src="https://img.shields.io/badge/PostgreSQL-pgvector-4169e1?logo=postgresql&logoColor=white">
</p>

<p><a href="README.en.md">English</a></p>

</div>

## Что это

Lecturo помогает учиться по записям лекций. Вы загружаете видео файлом или ссылкой, а сервис распознаёт речь и собирает из неё материалы для подготовки. Лекции объединяются в курсы, по курсу можно искать и собрать памятку к экзамену.

- Расшифровка с таймкодами: клик по фразе открывает видео с этого места.
- Главы и конспект. В конспекте есть формулы LaTeX и цветные блоки для определений, теорем, примеров и важных замечаний.
- Квиз по лекции, у каждого вопроса ссылка на момент видео, где об этом говорили.
- Памятка к экзамену по всему курсу.
- Поиск по смыслу и по словам сразу по всем лекциям, главам и конспектам.
- Экспорт в PDF, SRT и VTT.
- Публичная ссылка на лекцию или курс, чтобы поделиться с одногруппниками.
- Локальный режим: распознавание (Whisper) и конспект (WebLLM) считаются прямо в браузере, видео не уходит на сервер. Это бесплатно.
- Telegram Mini App и бот: вход через Telegram, уведомление, когда лекция готова.
- Сайт ставится как PWA, для Android есть APK.

Распознавание на сервере идёт через Yandex SpeechKit, конспект и квиз пишет LLM (DeepSeek или другой OpenAI-совместимый сервис), для поиска используются эмбеддинги Yandex. Оплата подписки и пакетов минут через ЮKassa. Чат с нейросетью по лекции пока в работе ([#306](https://github.com/DedAlexevich/Lecturo/issues/306)).

## Как это выглядит

<div align="center">
<a href="https://lecturo.ru"><img src="docs/assets/readme/demo.png" alt="Демо Lecturo" width="800"></a>
</div>

<table>
<tr>
<td width="50%"><img src="docs/assets/readme/lecture.png" alt="Страница лекции"><p align="center">Страница лекции</p></td>
<td width="50%"><img src="docs/assets/readme/summary.png" alt="Конспект с формулами"><p align="center">Конспект с формулами</p></td>
</tr>
<tr>
<td><img src="docs/assets/readme/quiz.png" alt="Квиз"><p align="center">Квиз</p></td>
<td><img src="docs/assets/readme/search.png" alt="Поиск по курсу"><p align="center">Поиск по курсу</p></td>
</tr>
<tr>
<td><img src="docs/assets/readme/mini-app.png" alt="Telegram Mini App"><p align="center">Telegram Mini App</p></td>
<td><img src="docs/assets/readme/local.png" alt="Локальный режим"><p align="center">Локальный режим</p></td>
</tr>
</table>

## Как устроено

```mermaid
flowchart LR
    user["Браузер, PWA, APK"] --> caddy["Caddy, HTTPS"]
    tg["Telegram"] --> caddy
    tg --> bot["Бот, aiogram"]
    caddy --> front["Фронтенд, React"]
    caddy --> api["API, FastAPI"]
    caddy --> tusd["tusd, загрузка файлов"]
    tusd --> files[("Файлы лекций, data/storage")]
    api --> db[("PostgreSQL и pgvector")]
    api --> redis[("Redis, очередь arq")]
    api --> files
    api --> yookassa["ЮKassa"]
    redis --> worker["Воркер, arq"]
    worker --> db
    worker --> files
    worker --> stt["Yandex SpeechKit"]
    worker --> llm["LLM, DeepSeek"]
    worker --> emb["Эмбеддинги Yandex"]
    worker -->|события лекций| redis
    redis --> bot
    bot --> tg
    bot --> db
    user -.->|локальный режим| local["Whisper и WebLLM в браузере"]
```

Пользователь загружает видео через tusd или даёт ссылку. API ставит задачу в очередь, воркер скачивает видео, пережимает его, отправляет аудио на распознавание, собирает главы, конспект и эмбеддинги для поиска. Когда лекция готова, воркер публикует событие, и бот присылает уведомление. Подробнее о шагах обработки: [backend/app/pipeline/README.md](backend/app/pipeline/README.md).

## Стек

| Часть | Что используем |
|---|---|
| Бэкенд | Python 3.12, FastAPI, SQLAlchemy, Alembic, arq |
| База | PostgreSQL 16 и pgvector, Redis |
| Фронтенд | React 18, TypeScript, Vite, KaTeX, vite-plugin-pwa |
| В браузере | Whisper через Transformers.js, WebLLM |
| Бот | aiogram 3 |
| Провайдеры | Yandex SpeechKit, DeepSeek или другой OpenAI-совместимый LLM, эмбеддинги Yandex |
| Оплата | ЮKassa |
| Инфраструктура | Docker Compose, Caddy, tusd, GitHub Actions |
| Android | Trusted Web Activity, Bubblewrap |

## Быстрый старт

Нужны Docker и Docker Compose.

```
cp .env.example .env
docker compose up --build
```

Сайт откроется на http://localhost, документация API на http://localhost/api/docs.

По умолчанию провайдеры распознавания, LLM и эмбеддингов работают в режиме `stub`: возвращают тестовые данные, ключи не нужны. Чтобы подключить настоящие, задайте `STT_PROVIDER`, `LLM_PROVIDER`, `EMBEDDINGS_PROVIDER` и ключи в `.env`. Описание всех переменных и инструкции по получению ключей: [docs/env.md](docs/env.md).

## Свой сервер

Тот же `docker compose` работает и на сервере. Для HTTPS укажите домен в `SITE_ADDRESS`, Caddy сам получит сертификат. Первая настройка сервера, автодеплой, почта, мониторинг и бэкапы описаны в [docs/deploy.md](docs/deploy.md).

- Данные (база, файлы лекций) хранятся в папке `data/` рядом с проектом и переживают `docker compose down -v`. Подробности и перенос из старых томов: [docs/data.md](docs/data.md).
- Логи сервисов лежат в `data/logs` с ротацией: [docs/logs.md](docs/logs.md).
- Раз в сутки контейнер `db-backup` сохраняет дамп базы в `data/backups` (7 копий). Ручной дамп, восстановление и проверка: [docs/backups.md](docs/backups.md).

## Документация

Всё собрано в [docs/README.md](docs/README.md):

- [Переменные окружения и ключи](docs/env.md)
- [Деплой на сервер](docs/deploy.md)
- [Хранение данных](docs/data.md)
- [Логи](docs/logs.md)
- [Бэкапы базы](docs/backups.md)
- [Сценарий демо](docs/demo.md)
- [Конвейер обработки](backend/app/pipeline/README.md)
- [Инфраструктура](infra/README.md)

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
| `frontend/src/local` | локальная обработка в браузере |
| `frontend/src/telegram` | Telegram Mini App |
| `bot` | Telegram-бот |
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

## Как внести вклад

Задачи и баги ведём в [issues](https://github.com/DedAlexevich/Lecturo/issues), код обсуждаем в pull request. Перед первым PR прочитайте [CONTRIBUTING.md](CONTRIBUTING.md): там про ветки, формат коммитов и проверки CI.

## Команда

| Участник | |
|---|---|
| [@DedAlexevich](https://github.com/DedAlexevich) | владелец репозитория |
| [@AxellorWave](https://github.com/AxellorWave) | разработка |
| [@aaaa24](https://github.com/aaaa24) | разработка |
| [@vamaria06-ux](https://github.com/vamaria06-ux) | разработка |
| [@elizazha](https://github.com/elizazha) | разработка |

Кто за какую часть отвечает, написано в issue [«Зоны и ответственные»](https://github.com/DedAlexevich/Lecturo/issues/1).

## Лицензия

AGPL-3.0, см. [LICENSE](LICENSE). Если вы запускаете изменённую версию Lecturo как сервис, исходники изменений нужно открыть пользователям этого сервиса.
