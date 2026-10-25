# Railway: запуск EveryKYC

Репозиторий: [veetma0/everykyc_bot](https://github.com/veetma0/everykyc_bot). Ветка: `main`. Рабочая папка на Mac: `Desktop/everykyc`.

## Настройки

| Параметр | Значение |
| --- | --- |
| Тип | Постоянно работающий Telegram polling worker |
| Сборка | `Dockerfile` из корня |
| Запуск | `python -m verifydesk` |
| Реплики | 1 |
| Volume, Mount Path | `/app/data` |
| `DATA_DIR` | `/app/data` |
| Сон / Serverless | Выключен |
| Cron | Не задан |
| HTTP Healthcheck / домен | Не требуются для этого worker |

Настройки сборки, запуска, одного экземпляра, перезапуска, ожидания Volume и завершения процесса заданы в `railway.json`. При отсутствии реального Volume бот останавливается до обращения к Telegram. Переменная `RAILWAY_VOLUME_MOUNT_PATH` создаётся Railway при подключении Volume: не добавляйте её вручную.

## Порядок подключения

1. Railway → **New Project → Deploy from GitHub repo** → `veetma0/everykyc_bot`.
2. В сервисе подключите **Volume**, путь монтирования **`/app/data`**. Настройте автоматические резервные копии Volume.
3. Откройте **Variables → RAW Editor**. На этом Mac готов личный файл **`.env.railway`**: скопируйте его содержимое целиком. Он содержит действующие секреты и исключён из Git. Для чужой установки используйте `.env.railway.example`, заменив токен и числовые ID операторов.
4. Проверьте **Settings**: корень репозитория `/`, Dockerfile, одна реплика, сон выключен. Не добавляйте HTTP healthcheck или cron. Публичный домен для Telegram polling не нужен.
5. До запуска облачной копии остановите локальную: `.venv/bin/python manage_service.py stop`. Один токен не должен одновременно использоваться локальным и облачным polling-процессами.
6. Если нужна прежняя переписка, перенесите свежую согласованную копию базы на Volume **до рабочего запуска** по разделу ниже. Иначе новый Volume начнёт с пустой базы.
7. Выполните **Deploy / Redeploy**. В логах должна появиться строка `Бот запущен: @everykyc_bot`. Проверьте отсутствие `409`, `ERROR` и повторных перезапусков. Затем откройте бот, `/start`, а оператору — `/admin` и `/next`.

`RAILWAY_RUN_UID=0` включён в профиль: у нового Railway Volume могут быть права root, тогда обычный пользователь Docker-образа не может записать базу. Это официальный способ Railway для таких образов. Локальный Docker по умолчанию продолжает работать под пользователем `bot`. [Railway Volumes](https://docs.railway.com/volumes/reference).

## Перенос существующей базы

Локальные база и сообщения не публикуются в GitHub и не входят в Docker-образ. Для окончательного переключения сначала остановите локальный бот, затем создайте свежий SQLite backup. Не копируйте один `desk.sqlite3` из работающей базы в режиме WAL: недавние записи могут находиться в другом файле.

Из корня проекта:

```sh
.venv/bin/python manage_service.py stop
.venv/bin/python - <<'PY'
from pathlib import Path
import os
import sqlite3
from datetime import datetime, timezone

os.umask(0o077)
directory = Path('.local/backups')
directory.mkdir(parents=True, exist_ok=True)
stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
destination = directory / f'railway-transfer-{stamp}.sqlite3'
with sqlite3.connect('data/desk.sqlite3') as source, sqlite3.connect(destination) as backup:
    source.backup(backup)
    assert backup.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
print(destination)
PY
```

На подключённый Volume загрузите этот backup как `/app/data/desk.sqlite3`, пока облачный worker остановлен. Для работы с файлами используйте поддерживаемый вашим аккаунтом инструмент Railway Volume; свежая документация описывает `railway volume files` / `railway volume browse`. Установленная на этом Mac версия CLI пока не поддерживает эти команды: не используйте неподтверждённые команды загрузки. До переноса сохраните исходную базу и резервную копию локально. [Управление Volume](https://docs.railway.com/volumes/reference).

После переноса сравните количество пользователей, заявок и сообщений, затем проверьте старую заявку и переписку. Включать обе копии для сравнения нельзя. Если переключение откладывается, локальную копию можно вернуть командой `.venv/bin/python manage_service.py install`; перед облачным запуском снова остановите её и создайте свежий backup.

## Проверки перед публикацией

```sh
.venv/bin/python -m ruff check .
.venv/bin/python -m pytest -q
.venv/bin/python -m verifydesk.deployment
docker build -t everykyc:local .
```

Проверка `verifydesk.deployment` использует временную SQLite-базу внутри каталога данных и не запускает Telegram. При реальном запуске эта проверка выполняется автоматически.

GitHub Actions проверяет Python 3.11/3.12, Ruff, тесты, сборку Docker, работу без сети и запись/чтение одного Volume в двух отдельных контейнерах. Реальный токен в CI не нужен. `.env`, `.env.railway`, `data/`, `.local/`, журналы, база и приватный скриншот не отправляются в GitHub. Docker-контекст содержит только код и зависимости.

## Статус подготовки

Локально прошли **227 тестов** и Ruff. Docker-образ собран; проверены запуск без сети и сохранность тестовой базы, сообщений и закрепления оператора между отдельными контейнерами. Локальный сервис перенесён в `Desktop/everykyc`; все десять таблиц рабочей базы сохранены.

Вход в Railway на этом Mac не выполнен. Облачный проект, Volume, переменные и сам деплой этой подготовкой не создавались. Успешная сборка или состояние Active сами по себе не доказывают, что бот работает в облаке: требуются проверка логов и настоящего диалога после подключения.

Настройки сверены с [Config as Code](https://docs.railway.com/config-as-code/reference), [официальной схемой railway.json](https://railway.com/railway.schema.json) и [Railway Volumes](https://docs.railway.com/volumes/reference).
