# infra

| Файл | Что это |
|---|---|
| `server-setup.sh` | первая настройка сервера, см. [docs/deploy.md](../docs/deploy.md#первая-настройка) |
| `deploy.sh` | выкладка коммита на сервер, запускается из GitHub Actions |
| `compose.prod.yml` | настройки compose для сервера |
| `Caddyfile` | конфигурация Caddy |
| `mail/` | образ сервиса `mail`: Postfix и OpenDKIM для писем сайта, см. [docs/deploy.md](../docs/deploy.md#почта) |
| `status.sh`, `health-alert.sh`, `install-monitoring.sh` | сводка по серверу и алерты в Telegram, см. [docs/deploy.md](../docs/deploy.md#мониторинг-и-логи) |
| `backup/` | бэкапы базы, см. ниже |

## Бэкапы базы

- `backup/backup.sh` делает дамп в `BACKUP_DIR` и проверяет его через `check.sh`. Если задан `BACKUP_AGE_RECIPIENT`, шифрует его вместе с ключом DKIM в `.tar.age` и выгружает в Object Storage (`BACKUP_S3_*`). Оставляет последние `BACKUP_KEEP` копий.
- `backup/check.sh [файл]` восстанавливает указанный или последний незашифрованный `.dump` во временный Postgres и проверяет, что база читается. Архивы `.tar.age` он не проверяет: приватного ключа на сервере нет.
- `backup/restore.sh <файл>` заменяет базу проекта дампом или архивом `.tar.age` (с `BACKUP_AGE_IDENTITY`), предварительно сохранив текущую.
- `backup/lecturo-backup.service` и `backup/lecturo-backup.timer` запускают бэкап раз в сутки на сервере, `backup/lecturo-alert@.service` присылает в Telegram сообщение, если бэкап упал (`notify.sh`, `unit-failed.sh`).
- `backup/schedule.sh` крутится в контейнере `db-backup` локального стенда и делает дамп по расписанию, см. [docs/backups.md](../docs/backups.md).
- `backup/common.sh` содержит общие функции. По умолчанию скрипты подключаются к сервису `db` через `docker compose exec`. Другой сервис задаётся `BACKUP_DB_SERVICE`, отдельный контейнер `BACKUP_DB_CONTAINER`.

Как включить на сервере, проверить и восстановить базу: [docs/deploy.md](../docs/deploy.md#бэкапы-базы). Переменные: [docs/env.md](../docs/env.md).
