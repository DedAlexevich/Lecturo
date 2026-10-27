# Деплой на сервер

Сервер: Ubuntu 24.04, от 2 ГБ RAM, A-запись домена указывает на IP сервера.

## Первая настройка

С компьютера администратора, пока вход по паролю root ещё работает:

```sh
ssh-copy-id root@<ip>
scp infra/server-setup.sh root@<ip>:
ssh root@<ip> "bash server-setup.sh <домен> '$(cat ~/.ssh/id_ed25519.pub)'"
```

Скрипт ставит Docker, ufw (22, 80, 443), fail2ban, swap, создаёт пользователя `deploy` для GitHub Actions, клонирует репозиторий в `/opt/lecturo` и создаёт `.env` со случайными `SECRET_KEY` и `POSTGRES_PASSWORD`. Для администратора создаётся пользователь `admin`, он входит только по ключу. Вход root по ssh и вход по паролю выключаются, права root берутся через `su -` с паролем root. Перед тем как закрыть текущую сессию, проверьте вход в новом окне: `ssh admin@<ip>`.

В конце скрипт печатает значения для GitHub Secrets (Settings → Secrets and variables → Actions):

| Секрет | Что это |
|---|---|
| `SSH_HOST` | IP сервера |
| `SSH_USER` | `deploy` |
| `SSH_KEY` | приватный ключ `deploy`, которым можно только запустить `infra/deploy.sh`; печатается один раз, на сервере не хранится |
| `SSH_KNOWN_HOSTS` | ключ хоста, чтобы Actions не доверял подменённому серверу |
| `DEPLOY_URL` | `https://<домен>`, по нему проверяется `/api/v1/health` |

Если ключ потерян, запустите скрипт ещё раз: он выдаст новый ключ, старый перестанет работать, `.env` останется прежним. После первого запуска root по ssh не пускает, поэтому повторно так:

```sh
scp infra/server-setup.sh admin@<ip>:
ssh -t admin@<ip> "su - -c \"bash /home/admin/server-setup.sh <домен> '$(cat ~/.ssh/id_ed25519.pub)'\""
```

## Ключи сервисов

Заполните в `/opt/lecturo/.env` ключи провайдеров, бота, OAuth, ЮKassa и SMTP (описание в [env.md](env.md)), затем первый запуск:

```sh
ssh admin@<ip>
su -
su - deploy -c /opt/lecturo/infra/deploy.sh
```

Проверка: `curl https://<домен>/api/v1/health`.

## Автодеплой

Workflow `Deploy` запускается после зелёного CI на `main`: заходит на сервер как `deploy` и выполняет `infra/deploy.sh <sha>`. Скрипт обновляет код и пересобирает контейнеры, миграции применяются при старте api. Если контейнеры не стали healthy, миграции откатываются (`alembic downgrade` до прежней ревизии), код возвращается на прошлый коммит и поднимается заново, а workflow становится красным. Поэтому у каждой миграции должен работать `downgrade`. Коммит старее уже выложенного не выкладывается. Ручной запуск (Actions → Deploy → Run workflow) выкладывает свежий `main`.

## Данные на сервере

База и файлы лежат в `/opt/lecturo/data` (переменная `DATA_DIR`), подробности в [data.md](data.md). `infra/deploy.sh` эту папку не трогает. Если сервер раньше работал на именованных томах Docker, перед первым деплоем с этой версией остановите проект и перенесите данные: `cd /opt/lecturo && docker compose down && ./scripts/migrate-volumes.sh`, иначе проект стартует с пустой базой (старые тома при этом остаются).

## Мониторинг и логи

Ротация логов контейнеров описана в #246. Смотреть логи: `docker compose logs -f --tail 200 api worker`.

Сводка по серверу одной командой (под `deploy`, из `/opt/lecturo`):

```sh
infra/status.sh
```

Скрипт показывает состояние сервисов, ответ `/api/v1/health`, длину очереди arq (`queued` ждут воркера, `in progress` обрабатываются), место на диске и в Docker, память и ошибки из логов `api`, `worker` и `bot` за последний час.

Проверку здоровья запускает systemd-таймер `lecturo-health.timer` раз в минуту от пользователя `deploy`: `infra/health-alert.sh` запрашивает `PUBLIC_URL/api/v1/health`. После трёх неудач подряд владельцу приходит сообщение в Telegram со списком сервисов и их статусами, после восстановления приходит ещё одно. Пока идёт деплой, проверка пропускается. Сообщения отправляет бот проекта (`TELEGRAM_BOT_TOKEN`) в чат `ALERT_TELEGRAM_CHAT_ID`:

1. Напишите боту `/start` с аккаунта владельца, иначе Telegram не даст боту писать первым.
2. Узнайте свой числовой id: для личного чата `chat_id` совпадает с id пользователя Telegram. Если вы входили на сайт через Telegram, он есть в базе: `docker compose exec db psql -U lecturo -c "select email, telegram_chat_id from users where telegram_chat_id is not null"`.
3. Впишите его в `/opt/lecturo/.env`: `ALERT_TELEGRAM_CHAT_ID=<id>`.

`infra/server-setup.sh` ставит таймер сам. На сервере, настроенном раньше, поставьте его вручную под root: `bash /opt/lecturo/infra/install-monitoring.sh`. Повторный запуск `server-setup.sh` для этого не нужен, он заодно перевыпустит ключ деплоя.

Проверить алерт: `docker compose stop api`, через 3–4 минуты должно прийти сообщение, затем `docker compose start api`. Статус таймера и последние проверки: `systemctl list-timers lecturo-health.timer` и `journalctl -u lecturo-health -n 20`.

## Бэкапы базы

Раз в сутки (около 03:30 UTC) таймер systemd `lecturo-backup.timer` от пользователя `deploy` запускает `infra/backup/backup.sh`, а затем `infra/backup/check.sh`.

- `backup.sh` делает `pg_dump` в формате custom из контейнера `db` и кладёт файл `lecturo-<дата>-<время>.dump` в папку `BACKUP_DIR` на хосте (по умолчанию `/opt/lecturo/backups`), то есть вне контейнера и вне `data/postgres`. Файл сначала пишется во временный, проверяется через `pg_restore --list` и только потом переименовывается. Хранятся последние `BACKUP_KEEP` копий (по умолчанию 7), старые удаляются. Папка и файлы доступны только `deploy` (права `700` и `600`).
- `check.sh [файл]` поднимает временный контейнер Postgres без сети (`lecturo-backup-check`, образ как у `db`), восстанавливает в него последний бэкап или указанный файл и печатает ревизию миграций, число таблиц и пользователей. Если восстановление не прошло, сервис завершается с ошибкой. Контейнер удаляется в любом случае.
- Пока идёт деплой, бэкап ждёт его окончания (та же блокировка, что в `infra/deploy.sh`).

На новом сервере таймер ставит `infra/server-setup.sh`. На уже настроенном сервере после деплоя с этой версией один раз выполните под root:

```sh
install -m 644 /opt/lecturo/infra/backup/lecturo-backup.service /opt/lecturo/infra/backup/lecturo-backup.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now lecturo-backup.timer
systemctl start lecturo-backup.service
```

Юниты копируются, а не подключаются ссылкой на репозиторий: файлы в `/opt/lecturo` может менять `deploy`, а юнит systemd от его имени менять нельзя.

Проверка:

```sh
systemctl list-timers lecturo-backup.timer
journalctl -u lecturo-backup.service -n 20
ls -l /opt/lecturo/backups
```

В журнале должна быть строка `ok ... revision ..., N tables, M users`.

Сообщений о сбое бэкапа нет, поэтому журнал стоит время от времени смотреть: при ошибке `systemctl status lecturo-backup.service` показывает `failed`. На новом сервере таймер включается до первого деплоя, и пока проект не запущен, ночные запуски падают на `docker compose exec db`. Это ожидаемо и проходит после первого деплоя.

Бэкапы лежат на том же диске, что и база: от удалённой строки или неудачной миграции они спасут, от потери сервера нет. Копию стоит регулярно уносить с сервера. Автоматической выгрузки пока нет: под root скопируйте свежий дамп в `/home/admin` (`install -m 600 -o admin /opt/lecturo/backups/lecturo-<дата>-<время>.dump /home/admin/`), заберите его `scp admin@<ip>:lecturo-*.dump .` и удалите с сервера. Ключ `deploy` для этого не подходит, он может запускать только `infra/deploy.sh`.

### Восстановление

```sh
ssh admin@<ip>
su -
su - deploy -c "/opt/lecturo/infra/backup/restore.sh /opt/lecturo/backups/lecturo-<дата>-<время>.dump"
```

Скрипт просит ввести `yes`, затем сохраняет текущую базу в `pre-restore-<дата>-<время>.dump` в той же папке (эти файлы не удаляются автоматически), останавливает `api`, `worker` и `bot`, пересоздаёт базу `lecturo`, восстанавливает дамп и поднимает сервисы обратно. Если дамп старее кода, недостающие миграции применит `api` при старте. Если восстановление упало, сервисы остаются остановленными, а скрипт печатает путь к сохранённой прежней базе: её можно вернуть тем же `restore.sh`.

Для `restore.sh` контейнер `db` должен работать. Если сама база повреждена и не запускается, остановите проект, переложите `data/postgres` в сторону, поднимите `db` с пустой папкой и восстановите бэкап.
