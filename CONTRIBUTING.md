# Как внести вклад

Спасибо, что решили помочь Lecturo. Ниже то, как у нас устроена работа. Всё общение идёт в GitHub: задачи и баги в issues, обсуждение кода в pull request.

## Issues

- Баг или идея — сначала issue. Шаблоны: [задача](.github/ISSUE_TEMPLATE/task.md) и [баг](.github/ISSUE_TEMPLATE/bug.md).
- Пишите на русском, коротко и по делу: что происходит, как воспроизвести, что ожидали.
- Кто за какую часть отвечает, написано в [#1 «Зоны и ответственные»](https://github.com/DedAlexevich/Lecturo/issues/1). Чтобы позвать человека, упомяните его логин в комментарии.

Лейблы:

| Лейбл | Что значит |
|---|---|
| `area:<зона>` | часть проекта: `backend`, `pipeline`, `frontend`, `local`, `bot-devops`, `legal` |
| `type:feature`, `type:bug`, `type:question` | тип задачи |
| `type:contract-change` | меняется общий контракт: схема API, модели, миграции |
| `needs:<зона>` | нужен ответ от этой зоны |
| `priority:high` | важно сделать первым |

## Ветки и коммиты

Ветка от свежего `main`, имя `<номер issue>-<коротко-латиницей>`:

```
git switch main && git pull
git switch -c 123-export-srt
```

Коммиты в формате [Conventional Commits](https://www.conventionalcommits.org/ru/) на русском: `тип(область): что сделано`.

- типы: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `ci`, `style`;
- область: зона или модуль, например `backend`, `pipeline`, `frontend`, `bot`;
- пример: `fix(backend): продление подписки до конца оплаченной цепочки`.

Лучше несколько небольших коммитов, чем один большой. Добавляйте файлы явно, без `git add .`.

## Pull request

- Заголовок в формате коммита: после squash-мержа он станет коммитом в `main`.
- В описании `Closes #<номер>`, что сделано и как проверить. Шаблон подставится сам.
- Мержим squash-ом и только при зелёном CI.
- При конфликте влейте свежий `main` в свою ветку.

## Стиль кода

- В коде нет комментариев и docstring, кроме служебных директив вроде `# noqa`. Это проверяют `scripts/check_comments.py` и `npm run check:comments`.
- Python: `ruff check .` и `ruff format --check .`.
- Фронтенд: `npm run lint`, типы API генерируются из `backend/openapi.json` командой `npm run gen:api`.
- Модели, миграции, схемы API и `backend/app/core` меняем только через issue `type:contract-change`.

## Проверки перед PR

Команды для бэкенда, бота и фронтенда собраны в [docs/README.md](docs/README.md#быстрый-старт-для-разработчика). Полный прогон, включая сборку стенда в Docker, делает CI.

## Лицензия

Код проекта распространяется по [AGPL-3.0](LICENSE). Отправляя PR, вы соглашаетесь, что ваши изменения будут под этой же лицензией.
