<div align="center">

<img src="frontend/public/favicon.svg" alt="Lecturo" width="96" height="96">

<h1>Lecturo</h1>

<p>Turns lecture videos into a timestamped transcript, chapters, notes, a quiz and an exam cheat sheet.</p>

<p>
<a href="https://lecturo.ru"><img alt="Website" src="https://img.shields.io/badge/Website-lecturo.ru-14161a?style=for-the-badge"></a>
<a href="docs/README.md"><img alt="Docs" src="https://img.shields.io/badge/Docs-14161a?style=for-the-badge"></a>
<a href="docs/deploy.md"><img alt="Deploy" src="https://img.shields.io/badge/Deploy-14161a?style=for-the-badge"></a>
<a href="https://t.me/lecturo_notes_bot"><img alt="Telegram bot" src="https://img.shields.io/badge/Telegram%20bot-6ea5f2?style=for-the-badge&logo=telegram&logoColor=white"></a>
<a href="https://github.com/DedAlexevich/Lecturo/issues/new/choose"><img alt="Report an issue" src="https://img.shields.io/badge/Report%20an%20issue-14161a?style=for-the-badge"></a>
</p>

<p>
<a href="https://github.com/DedAlexevich/Lecturo/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/DedAlexevich/Lecturo/actions/workflows/ci.yml/badge.svg?branch=main"></a>
<a href="LICENSE"><img alt="License AGPL-3.0" src="https://img.shields.io/badge/license-AGPL--3.0-blue"></a>
<img alt="Python 3.12" src="https://img.shields.io/badge/Python-3.12-3776ab?logo=python&logoColor=white">
<img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white">
<img alt="React 18" src="https://img.shields.io/badge/React-18-61dafb?logo=react&logoColor=black">
<img alt="TypeScript" src="https://img.shields.io/badge/TypeScript-3178c6?logo=typescript&logoColor=white">
<img alt="PostgreSQL and pgvector" src="https://img.shields.io/badge/PostgreSQL-pgvector-4169e1?logo=postgresql&logoColor=white">
</p>

<p><a href="README.md">Русский</a></p>

</div>

## What it is

Lecturo helps you study from lecture recordings. Upload a video file or paste a link, and the service transcribes the speech and builds study materials from it. Lectures are grouped into courses that you can search and turn into an exam cheat sheet. The interface is in Russian.

- Timestamped transcript: click a phrase to jump to that moment in the video.
- Chapters and notes with LaTeX formulas and highlighted blocks for definitions, theorems, examples and key remarks.
- A quiz for each lecture, every question links to the moment in the video.
- An exam cheat sheet for the whole course.
- Semantic and keyword search across all lectures, chapters and notes.
- Export to PDF, SRT and VTT.
- Public links to share a lecture or a course.
- Local mode: speech recognition (Whisper) and notes (WebLLM) run in the browser, the video never leaves the device. It is free.
- Telegram Mini App and bot: sign in with Telegram and get notified when a lecture is ready.
- Installable as a PWA, APK for Android.

Server-side recognition uses Yandex SpeechKit, notes and quizzes are written by an LLM (DeepSeek or another OpenAI-compatible service), search uses Yandex embeddings. Payments go through YooKassa. A chat about the lecture is in progress ([#306](https://github.com/DedAlexevich/Lecturo/issues/306)).

## Screenshots

<div align="center">
<a href="https://lecturo.ru"><img src="docs/assets/readme/demo.gif" alt="Lecturo demo" width="800"></a>
</div>

<table>
<tr>
<td width="50%"><img src="docs/assets/readme/lecture.png" alt="Lecture page"><p align="center">Lecture page</p></td>
<td width="50%"><img src="docs/assets/readme/summary.png" alt="Notes with formulas"><p align="center">Notes with formulas</p></td>
</tr>
<tr>
<td width="50%"><img src="docs/assets/readme/quiz-question.png" alt="Quiz"><p align="center">Quiz</p></td>
<td width="50%"><img src="docs/assets/readme/quiz.png" alt="Answer explanation with a link to the lecture moment"><p align="center">Answer explanation with a link to the lecture moment</p></td>
</tr>
<tr>
<td width="50%"><img src="docs/assets/readme/chapters.png" alt="Chapters with timecodes"><p align="center">Chapters with timecodes</p></td>
<td width="50%"><img src="docs/assets/readme/local.png" alt="Local mode"><p align="center">Local mode</p></td>
</tr>
</table>

## Architecture

```mermaid
flowchart LR
    user["Browser, PWA, APK"] --> caddy["Caddy, HTTPS"]
    tg["Telegram"] --> caddy
    tg --> bot["Bot, aiogram"]
    caddy --> front["Frontend, React"]
    caddy --> api["API, FastAPI"]
    caddy --> tusd["tusd, uploads"]
    tusd --> files[("Lecture files, data/storage")]
    api --> db[("PostgreSQL and pgvector")]
    api --> redis[("Redis, arq queue")]
    api --> files
    api --> yookassa["YooKassa"]
    redis --> worker["Worker, arq"]
    worker --> db
    worker --> files
    worker --> stt["Yandex SpeechKit"]
    worker --> llm["LLM, DeepSeek"]
    worker --> emb["Yandex embeddings"]
    worker -->|lecture events| redis
    redis --> bot
    bot --> tg
    bot --> db
    user -.->|local mode| local["Whisper and WebLLM in the browser"]
```

## Stack

| Part | Tools |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy, Alembic, arq |
| Storage | PostgreSQL 16 with pgvector, Redis |
| Frontend | React 18, TypeScript, Vite, KaTeX, vite-plugin-pwa |
| In the browser | Whisper via Transformers.js, WebLLM |
| Bot | aiogram 3 |
| Providers | Yandex SpeechKit, DeepSeek or another OpenAI-compatible LLM, Yandex embeddings |
| Payments | YooKassa |
| Infrastructure | Docker Compose, Caddy, tusd, GitHub Actions |
| Android | Trusted Web Activity, Bubblewrap |

## Quick start

You need Docker and Docker Compose.

```
cp .env.example .env
docker compose up --build
```

The site runs at http://localhost, the API docs at http://localhost/api/docs.

By default the speech, LLM and embeddings providers run in `stub` mode and return test data, no keys needed. To use real providers set `STT_PROVIDER`, `LLM_PROVIDER`, `EMBEDDINGS_PROVIDER` and the keys in `.env`, see [docs/env.md](docs/env.md).

## Self-hosting

The same `docker compose` setup runs on a server. Put your domain into `SITE_ADDRESS` and Caddy will get a certificate. Server setup, auto-deploy, mail, monitoring and backups are described in [docs/deploy.md](docs/deploy.md). Data lives in `data/` next to the project ([docs/data.md](docs/data.md)), logs in `data/logs` ([docs/logs.md](docs/logs.md)), daily database dumps in `data/backups` ([docs/backups.md](docs/backups.md)).

## Documentation

The index is [docs/README.md](docs/README.md). The documents are in Russian.

## Team

[@DedAlexevich](https://github.com/DedAlexevich) (owner), [@AxellorWave](https://github.com/AxellorWave), [@aaaa24](https://github.com/aaaa24), [@vamaria06-ux](https://github.com/vamaria06-ux), [@elizazha](https://github.com/elizazha).

## License

AGPL-3.0, see [LICENSE](LICENSE).
