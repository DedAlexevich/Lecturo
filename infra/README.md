# infra

| Файл | Что это |
|---|---|
| `server-setup.sh` | первая настройка сервера, см. [docs/deploy.md](../docs/deploy.md#первая-настройка) |
| `deploy.sh` | выкладка коммита на сервер, запускается из GitHub Actions |
| `compose.prod.yml` | настройки compose для сервера |
| `Caddyfile` | конфигурация Caddy |
| `backup/` | бэкапы базы, см. ниже |

## Бэкапы базы

- `backup/backup.sh` делает дамп в `BACKUP_DIR` и оставляет последние `BACKUP_KEEP` копий.
- `backup/check.sh [файл]` восстанавливает последний или указанный дамп во временный Postgres и проверяет, что база читается.
- `backup/restore.sh <файл>` заменяет базу проекта дампом, предварительно сохранив текущую.
- `backup/lecturo-backup.service` и `backup/lecturo-backup.timer` запускают бэкап и проверку раз в сутки на сервере.
- `backup/common.sh` содержит общие функции. По умолчанию скрипты подключаются к сервису `db` через `docker compose exec`. Другой сервис задаётся `BACKUP_DB_SERVICE`, отдельный контейнер `BACKUP_DB_CONTAINER`.

Как включить на сервере, проверить и восстановить базу: [docs/deploy.md](../docs/deploy.md#бэкапы-базы). Переменные: [docs/env.md](../docs/env.md).
