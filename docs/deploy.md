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
