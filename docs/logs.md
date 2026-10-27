# Логи

Каждый сервис пишет логи в файл `data/logs/<сервис>.log` (папка внутри `DATA_DIR`, см. [data.md](data.md)) и продолжает выводить их в stdout, поэтому `docker compose logs` работает как раньше. Файлы переживают пересоздание контейнеров и `docker compose down -v`.

| Файл | Сервис | Что внутри |
|---|---|---|
| `api.log` | `api` | запросы uvicorn, ошибки приложения, письма в режиме лога (при пустом `SMTP_HOST` там же ссылки подтверждения и сброса пароля), ошибки yt-dlp при проверке ссылки |
| `worker.log` | `worker` | задачи arq, ошибки шагов обработки лекций (с трейсбеками), ошибки ffmpeg и yt-dlp |
| `bot.log` | `bot` | работа Telegram-бота |
| `caddy.log` | `caddy` | служебные сообщения и access-лог прокси |
| `tusd.log` | `tusd` | запросы и ошибки загрузки файлов |
| `mail.log` | `mail` (только на сервере) | приём и доставка писем Postfix, подпись OpenDKIM |

Формат строк у `api`, `worker` и `bot`: время, уровень, сервис, логгер и сообщение.

```
2026-10-27 13:10:54,692 INFO api app.services.mail: Письмо для a@example.org: ...
```

`caddy`, `tusd` и `mail` пишут в собственных форматах.

## Ротация

Файл `api`, `worker` и `bot` ротируется средствами Python (`RotatingFileHandler`), `caddy`, `tusd` и `mail` пишутся через `infra/log-to-file.sh` с тем же правилом. Когда файл достигает `LOG_MAX_MB` мегабайт (по умолчанию 10), он переименовывается в `<сервис>.log.1`, прежние копии сдвигаются, а самая старая сверх `LOG_BACKUP_COUNT` (по умолчанию 5) удаляется. На каждый сервис уходит не больше `LOG_MAX_MB * (LOG_BACKUP_COUNT + 1)` МБ.

Запасной вариант: json-логи Docker для всех сервисов ограничены `max-size: 10m` и `max-file: 3`.

## Как смотреть

```
tail -f data/logs/api.log
grep ERROR data/logs/worker.log*
docker compose logs -f api worker
```

Файлы создаются от имени root внутри контейнеров, читать их можно без `sudo`, удалять и менять нельзя.

## Как это устроено

Для `api`, `worker` и `bot` путь и имя файла задают переменные `LOG_DIR` и `LOG_SERVICE` из `docker-compose.yml`. Без `LOG_DIR` (например, при запуске тестов или `uvicorn` на хосте) логи идут только в stdout. Для `caddy` и `tusd` `docker-compose.yml` заменяет точку входа на `infra/log-to-file.sh`: скрипт запускает сервис, копирует его вывод и в stdout, и в файл и ротирует файл.
