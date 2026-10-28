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

## Первый администратор

Админ-панель (`/admin` на сайте) открыта только администраторам, остальным и API, и страница отвечают как несуществующие. Права проверяются на сервере при каждом запросе.

Пользователь сначала регистрируется на сайте обычным способом (почта или Telegram). Затем права выдаются командой на сервере:

```sh
ssh admin@<ip>
su -
su - deploy -c "cd /opt/lecturo && docker compose exec api python -m app.cli make-admin <почта или Telegram id>"
```

Под `admin` вместо `docker compose exec api` пишите `docker exec lecturo-api-1`. Команда выдаёт права, даже если администраторы уже есть, и пишет запись в журнал действий.

Второй способ: в `/opt/lecturo/.env` указать `INITIAL_ADMINS=<почта или Telegram id>` (несколько через запятую) и перезапустить api (`docker compose up -d api`). Переменная срабатывает только пока в базе нет ни одного администратора, поэтому снятый в панели администратор после перезапуска права не получит. Если пользователь ещё не зарегистрирован, в логах api будет `INITIAL_ADMINS: user not found`, после регистрации перезапустите api ещё раз.

Дальше администраторы назначаются и снимаются в панели, раздел «Администраторы». Последнего администратора снять нельзя. Все назначения и снятия видны в разделе «Журнал действий».

## Автодеплой

Workflow `Deploy` запускается после зелёного CI на `main`: заходит на сервер как `deploy` и выполняет `infra/deploy.sh <sha>`. Скрипт обновляет код и пересобирает контейнеры, миграции применяются при старте api. Если контейнеры не стали healthy, миграции откатываются (`alembic downgrade` до прежней ревизии), код возвращается на прошлый коммит и поднимается заново, а workflow становится красным. Поэтому у каждой миграции должен работать `downgrade`. Коммит старее уже выложенного не выкладывается. Ручной запуск (Actions → Deploy → Run workflow) выкладывает свежий `main`.

## Данные на сервере

База и файлы лежат в `/opt/lecturo/data` (переменная `DATA_DIR`), подробности в [data.md](data.md). `infra/deploy.sh` эту папку не трогает.

## Почта

Письма сайта (подтверждение почты, сброс пароля) отправляет сервис `mail`: Postfix только на отправку и OpenDKIM для подписи. Он есть только в `infra/compose.prod.yml`. Порт наружу не открыт, письма принимаются только от контейнеров проекта. `api` отправляет через него с адреса `Lecturo <noreply@<домен>>`, если в `.env` не задан внешний SMTP (см. [env.md](env.md#почта-smtp)). Входящую почту `mail` не принимает, ящики домена остаются у почтового провайдера из MX-записи.

Домен берётся из `SITE_ADDRESS`, другой можно задать в `MAIL_DOMAIN`. Ключ DKIM создаётся при первом запуске в `data/mail/dkim` и дальше не меняется. Если папку удалить, появится новый ключ и запись DKIM в DNS придётся заменить.

Без записей DNS почтовые сервисы считают письма подозрительными: Gmail и Mail.ru отклоняют их или кладут в спам. Нужные значения печатает команда:

```sh
docker compose exec mail dns-records.sh
```

Под `admin` вместо `docker compose exec mail` пишите `docker exec lecturo-mail-1`.

| Запись | Где | Значение |
|---|---|---|
| SPF, TXT на домене | DNS домена | `v=spf1 a ~all`: отправлять можно с IP из A-записи. SPF-запись у домена должна быть одна. Если с ящиков почтового провайдера тоже отправляют письма, добавьте в неё его `include`, для Timeweb: `v=spf1 a include:_spf.timeweb.ru ~all` |
| DKIM, TXT на `mail._domainkey` | DNS домена | строка `v=DKIM1; k=rsa; p=...` из вывода команды целиком |
| DMARC, TXT на `_dmarc` | DNS домена | `v=DMARC1; p=none; adkim=r; aspf=r` |
| PTR для IP сервера | панель хостинга, раздел сети или IP-адресов сервера | домен, например `lecturo.ru` |

Ключ DKIM длиннее 255 символов. Если панель DNS не принимает такую строку, разбейте значение на несколько строк в кавычках подряд: `"v=DKIM1; k=rsa; p=MIIB..." "...остаток"`.

Записи появляются не сразу, обычно в течение часа. Проверка с любого компьютера: `dig +short TXT <домен>`, `dig +short TXT mail._domainkey.<домен>`, `dig +short -x <ip>`.

Тестовое письмо и лог доставки:

```sh
docker compose exec api python -c "import asyncio; from app.services.mail import send_mail; asyncio.run(send_mail('<ваш адрес>', 'Проверка', 'Проверка почты'))"
grep -E "status=|dkim" data/logs/mail.log | tail
```

Хостинг может закрывать исходящий порт 25, тогда письма висят в `status=deferred` с `Connection timed out`. Проверка с сервера: `nc -vz gmail-smtp-in.l.google.com 25`. Если соединения нет, порт открывают через поддержку хостинга.

Строка `status=sent` значит, что сервер получателя принял письмо. При `status=deferred` или `status=bounced` в скобках будет ответ сервера получателя с причиной. В заголовках полученного письма («Показать оригинал» в Gmail) должны быть `spf=pass` и `dkim=pass`. Недоставленные письма Postfix повторяет сутки, затем удаляет. Очередь: `docker compose exec mail postqueue -p`.

## Прокси для YouTube

С сервера в РФ YouTube недоступен, поэтому аудио по ссылкам YouTube скачивается через SOCKS5-прокси на зарубежном сервере. Через прокси идут только запросы yt-dlp к YouTube, сайт, база и файлы пользователей остаются на основном сервере.

На зарубежном сервере (Ubuntu) под root:

```sh
curl -fsSL https://raw.githubusercontent.com/DedAlexevich/Lecturo/main/infra/youtube-proxy-setup.sh | bash -s -- <ip основного сервера>
```

Скрипт ставит dante с входом по логину и паролю, включает ufw и открывает порт 1080 только для основного сервера. В конце он печатает строку `YOUTUBE_PROXY=...`, её нужно добавить в `/opt/lecturo/.env` на основном сервере и перезапустить `worker` и `api`. При повторном запуске пароль меняется, строку в `.env` тоже придётся обновить.

Проверка с основного сервера:

```sh
docker exec lecturo-worker-1 sh -c 'python -m yt_dlp --proxy "$YOUTUBE_PROXY" -f bestaudio -o "/tmp/yt.%(ext)s" https://www.youtube.com/watch?v=jNQXAC9IVRw && rm /tmp/yt.*'
```

Если YouTube отвечает «Sign in to confirm you're not a bot», значит IP прокси попал под проверку YouTube и нужен другой зарубежный сервер.

## Мониторинг и логи

Логи пишутся в файлы с ротацией, см. [logs.md](logs.md). Смотреть логи: `docker compose logs -f --tail 200 api worker`.

Сводка по серверу одной командой (под `deploy`, из `/opt/lecturo`):

```sh
infra/status.sh
```

Скрипт показывает состояние сервисов, ответ `/api/v1/health`, длину очереди arq (`queued` ждут воркера, `in progress` обрабатываются), место на диске и в Docker, память и ошибки из логов `api`, `worker` и `bot` за последний час.

Проверку здоровья запускает systemd-таймер `lecturo-health.timer` раз в минуту от пользователя `deploy`: `infra/health-alert.sh` запрашивает `PUBLIC_URL/api/v1/health`. После трёх неудач подряд владельцу приходит сообщение в Telegram со списком сервисов и их статусами, после восстановления приходит ещё одно. Пока идёт деплой, проверка пропускается. Сообщения отправляет бот проекта (`TELEGRAM_BOT_TOKEN`) в чат `ALERT_TELEGRAM_CHAT_ID`:

1. Напишите боту `/start` с аккаунта владельца, иначе Telegram не даст боту писать первым.
2. Узнайте свой числовой id: для личного чата `chat_id` совпадает с id пользователя Telegram. Если вы входили на сайт через Telegram, он есть в базе: `docker compose exec db psql -U lecturo -c "select email, telegram_chat_id from users where telegram_chat_id is not null"`.
3. Впишите его в `/opt/lecturo/.env`: `ALERT_TELEGRAM_CHAT_ID=<id>`.

Тот же скрипт следит за местом на диске: если раздел с `/`, `DATA_DIR` или `BACKUP_DIR` занят на 85% и больше, приходит сообщение со списком разделов, а когда место освободится, ещё одно. Чаще всего место занимают видео, логи и брошенные загрузки. Незавершённые загрузки tusd старше `UPLOAD_STALE_HOURS` (по умолчанию сутки) воркер удаляет из `data/storage/uploads` раз в час.

`infra/server-setup.sh` ставит таймер сам. На сервере, настроенном раньше, поставьте его вручную под root: `bash /opt/lecturo/infra/install-monitoring.sh`. Повторный запуск `server-setup.sh` для этого не нужен, он заодно перевыпустит ключ деплоя.

Проверить алерт: `docker compose stop api`, через 3–4 минуты должно прийти сообщение, затем `docker compose start api`. Статус таймера и последние проверки: `systemctl list-timers lecturo-health.timer` и `journalctl -u lecturo-health -n 20`.

## Бэкапы базы

На сервере бэкапы делает таймер systemd. Контейнер `db-backup` из `docker-compose.yml` нужен для локального стенда ([backups.md](backups.md)) и здесь не запускается: в `infra/compose.prod.yml` он вынесен в профиль `local`.

Раз в сутки (около 03:30 UTC) таймер systemd `lecturo-backup.timer` от пользователя `deploy` запускает `infra/backup/backup.sh`.

- `backup.sh` делает `pg_dump` в формате custom из контейнера `db` в папку `BACKUP_DIR` на хосте (по умолчанию `/opt/lecturo/backups`), то есть вне контейнера и вне `data/postgres`. Файл сначала пишется во временный, проверяется через `pg_restore --list` и только потом переименовывается.
- Затем дамп проверяется `check.sh`: временный контейнер Postgres без сети (`lecturo-backup-check`, образ как у `db`) восстанавливает его и печатает ревизию миграций, число таблиц и пользователей. Если восстановление не прошло, бэкап считается неудачным.
- Если задан `BACKUP_AGE_RECIPIENT`, дамп вместе с ключом DKIM из контейнера `mail` упаковывается в `lecturo-<дата>-<время>.tar.age`, зашифрованный [age](https://age-encryption.org) публичным ключом владельца. Незашифрованный дамп удаляется, приватного ключа на сервере нет. Без `BACKUP_AGE_RECIPIENT` остаётся обычный `lecturo-<дата>-<время>.dump`, а в журнале будет предупреждение.
- Зашифрованный архив выгружается в Yandex Object Storage (см. ниже). Если переменные `BACKUP_S3_*` не заданы, выгрузка пропускается с предупреждением, а локальный бэкап работает как обычно.
- Хранятся последние `BACKUP_KEEP` копий (по умолчанию 7), старые удаляются. Папка и файлы доступны только `deploy` (права `700` и `600`).
- Пока идёт деплой, бэкап ждёт его окончания (та же блокировка, что в `infra/deploy.sh`).

Если бэкап упал (база недоступна, проверка не прошла, выгрузка не удалась, не прочитался ключ DKIM), systemd запускает `lecturo-alert@lecturo-backup.service.service`, и владельцу приходит сообщение в Telegram с последними строками журнала. Сообщение отправляет `infra/notify.sh` теми же `TELEGRAM_BOT_TOKEN` и `ALERT_TELEGRAM_CHAT_ID`, что и проверка здоровья. Кроме того, `infra/health-alert.sh` раз в минуту смотрит на самый свежий файл в `BACKUP_DIR` и присылает одно сообщение, если он старше 26 часов, и ещё одно, когда свежий бэкап появится. На новом сервере такое сообщение придёт сразу после установки, пока первого бэкапа ещё нет.

На новом сервере таймер ставит `infra/server-setup.sh`. На уже настроенном сервере после деплоя с этой версией один раз выполните под root:

```sh
apt-get install -y age
install -m 644 /opt/lecturo/infra/backup/lecturo-backup.service /opt/lecturo/infra/backup/lecturo-backup.timer /opt/lecturo/infra/backup/lecturo-alert@.service /etc/systemd/system/
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

В журнале должны быть строки `ok ... revision ..., N tables, M users`, `encrypted ...` и `uploaded ...`. Проверить алерт: `docker compose stop db`, `systemctl start lecturo-backup.service`, должно прийти сообщение о сбое, затем `docker compose start db`.

На новом сервере таймер включается до первого деплоя, и пока проект не запущен, ночные запуски падают на `docker compose exec db` и присылают алерт. Это ожидаемо и проходит после первого деплоя.

### Ключ шифрования

Ключ создаётся один раз на компьютере владельца, не на сервере:

```sh
age-keygen -o lecturo-backup.key
```

Команда печатает публичный ключ `age1...`, он идёт в `/opt/lecturo/.env` как `BACKUP_AGE_RECIPIENT`. Файл `lecturo-backup.key` — приватный ключ: храните его вне сервера (менеджер паролей и копия на отдельном носителе). Без него бэкапы не расшифровать.

### Копия в Yandex Object Storage

Каждый зашифрованный архив загружается в отдельный бакет как `daily/<имя>`, а по воскресеньям ещё и как `weekly/<имя>`. Удаление делает правило жизненного цикла бакета, сервер объекты не удаляет и не читает. Загрузка идёт через `curl --aws-sigv4`, отдельный клиент S3 не нужен.

Что нужно создать в Yandex Cloud:

1. Отдельный бакет, не тот, где лежат файлы лекций (`YANDEX_STORAGE_BUCKET`). Доступ только по ключам, публичный доступ выключен.
2. Правила жизненного цикла: объекты с префиксом `daily/` удалять через 7 дней, с префиксом `weekly/` через 28 дней.
3. Сервисный аккаунт с ролью `storage.uploader` только на этот бакет: он может загружать объекты, но не читать и не удалять их.
4. Статический ключ доступа этого аккаунта.
5. В `/opt/lecturo/.env`: `BACKUP_S3_BUCKET`, `BACKUP_S3_ACCESS_KEY_ID`, `BACKUP_S3_SECRET_ACCESS_KEY`. `BACKUP_S3_ENDPOINT` и `BACKUP_S3_REGION` менять не нужно.

Файлы из Object Storage скачивает владелец своим аккаунтом из консоли Yandex Cloud.

### Восстановление

Приватный ключ на время восстановления нужно положить на сервер, а после удалить:

```sh
scp lecturo-backup.key admin@<ip>:
ssh admin@<ip>
su -
install -m 600 -o deploy /home/admin/lecturo-backup.key /home/deploy/lecturo-backup.key && shred -u /home/admin/lecturo-backup.key
su - deploy -c "BACKUP_AGE_IDENTITY=/home/deploy/lecturo-backup.key /opt/lecturo/infra/backup/restore.sh /opt/lecturo/backups/lecturo-<дата>-<время>.tar.age"
shred -u /home/deploy/lecturo-backup.key
```

Скрипт расшифровывает архив во временную папку внутри `BACKUP_DIR` (она удаляется по завершении), просит ввести `yes`, сохраняет текущую базу в `pre-restore-<дата>-<время>.tar.age` (или `.dump`, если `BACKUP_AGE_RECIPIENT` не задан) в той же папке, останавливает `api`, `worker` и `bot`, пересоздаёт базу `lecturo`, восстанавливает дамп и поднимает сервисы обратно. Файлов `pre-restore-*` хранится три последних. Если дамп старее кода, недостающие миграции применит `api` при старте. Если восстановление упало, сервисы остаются остановленными, а скрипт печатает путь к сохранённой прежней базе: её можно вернуть тем же `restore.sh`. Незашифрованный `.dump` скрипт тоже принимает, ключ для него не нужен.

Для `restore.sh` контейнер `db` должен работать. Если сама база повреждена и не запускается, остановите проект, переложите `data/postgres` в сторону, поднимите `db` с пустой папкой и восстановите бэкап.

Если сервер потерян, скачайте последний архив из бакета и расшифруйте его у себя:

```sh
age -d -i lecturo-backup.key lecturo-<дата>-<время>.tar.age | tar -xf -
```

Получатся `lecturo.dump` и `dkim.tar`. На новом сервере до первого запуска `mail` распакуйте ключ DKIM, чтобы не менять DNS-записи: `mkdir -p /opt/lecturo/data/mail/dkim && tar -xf dkim.tar -C /opt/lecturo/data/mail/dkim`. Базу восстановите командой выше, передав `lecturo.dump`.
