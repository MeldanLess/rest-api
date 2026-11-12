# Развёртывание

Как этот API доходит от коммита до публичного адреса.

**Схема целиком:** один Linux-сервер (хватит небольшого VPS), Docker с API и
PostgreSQL, nginx спереди терминирует TLS, а жизненным циклом управляет
systemd. Один и тот же `Dockerfile` работает локально, в CI и в бою — именно
ради этого он и один.

```
                    ┌──────────────────────────────────────────┐
   интернет ──TLS──▶│ nginx :443                              │
                    │   proxy_pass + заголовки безопасности    │
                    └───────────────┬──────────────────────────┘
                                    │ 127.0.0.1:8000
                    ┌───────────────▼──────────────────────────┐
                    │ контейнер api (uvicorn)                 │
                    │   alembic upgrade head && uvicorn ...    │
                    └───────────────┬──────────────────────────┘
                                    │ postgres://…@db:5432
                    ┌───────────────▼──────────────────────────┐
                    │ контейнер db (PostgreSQL 16)             │
                    │   наружу с хоста не публикуется           │
                    └──────────────────────────────────────────┘
```

---

## 1. Сервер

Подойдёт любой Linux-VPS с Docker — потребление памяти самим API небольшое, а
PostgreSQL с несколькими сотнями строк и того меньше. Важны две вещи:

- **Публичный IP и DNS-запись.** Направьте на него `api.example.com`.
- **Настоящий секретный ключ.** При `ENVIRONMENT=production` приложение
  намеренно отказывается стартовать с ключом по умолчанию.

```bash
# На сервере
sudo apt update && sudo apt install -y docker.io docker-compose-plugin git
sudo usermod -aG docker "$USER"   # выйдите из сессии и войдите снова
```

## 2. Код и конфигурация

```bash
sudo mkdir -p /opt/applytrack
sudo chown "$USER" /opt/applytrack
git clone https://github.com/MeldanLess/rest-api.git /opt/applytrack
cd /opt/applytrack

cp deploy/env.production.example env.production
cp deploy/docker-compose.prod.yml .
```

Заполните `env.production`:

| Переменная | Откуда взять |
|---|---|
| `POSTGRES_PASSWORD` | `openssl rand -base64 24` |
| `SECRET_KEY` | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `CORS_ORIGINS` | Домен вашего портфолио, если что-то из браузера ходит в API |
| `API_IMAGE` | Тег образа, опубликованный рабочим процессом релиза, например `ghcr.io/MeldanLess/rest-api:v1.0.0` |

Потом защитите файл — в нём пароль от базы и ключ подписи:

```bash
chmod 600 env.production
```

> Файл называется `env.production` и лежит **в корне репозитория**, а не в
> `deploy/`: боевой compose-файл копируется в корень (`cp deploy/docker-compose.prod.yml .`)
> и ищет переменные окружения по пути `./env.production`. Если положить файл
> в `deploy/`, compose не найдёт его и не запустится.

## 3. База данных

Схемой владеет Alembic, а не `create_all`. Compose-файл накатывает миграции до
старта API:

```bash
docker compose -f docker-compose.prod.yml up -d db
docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head
```

## 4. API как сервис systemd

```bash
sudo cp deploy/applytrack.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now applytrack

systemctl status applytrack
curl -s localhost:8000/health | python -m json.tool
```

`/health` сообщает о базе как `up` или `down`, а не падает сразу, поэтому
мониторинг может отличить «процесс жив, но база недоступна» от «процесса
нет».

## 5. nginx и TLS

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
sudo cp deploy/nginx.conf /etc/nginx/sites-available/applytrack
sudo ln -s /etc/nginx/sites-available/applytrack /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx

sudo certbot --nginx -d api.example.com
```

certbot переписывает `nginx.conf` на месте: добавляет перенаправление HTTP на
HTTPS и пути к сертификатам, которыми управляет сам. Обновление автоматическое;
`certbot renew --dry-run` проверяет таймер, ничего не трогая.

## 6. Резервные копии

База, из которой ни разу не разворачивали, не считается сохранённой. Таймер
снимает ночной сжатый дамп и хранит две недели таких копий:

```bash
sudo cp deploy/applytrack-backup.service deploy/applytrack-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now applytrack-backup.timer

systemctl list-timers applytrack-backup.timer
sudo systemctl start applytrack-backup.service   # выполнить прямо сейчас
```

**Проверьте восстановление до того, как оно понадобится.** Команда есть в
`deploy/backup.sh`:

```bash
gunzip -c backups/applytrack-<timestamp>.sql.gz \
  | docker compose -f docker-compose.prod.yml exec -T db psql -U applytrack applytrack
```

## 7. Выпуск новой версии

```bash
# Локально
git tag -a v1.0.0 -m "Первый публичный релиз"
git push origin v1.0.0
```

Рабочий процесс `Publish image` тестирует код, собирает образ и отправляет его
в GitHub Container Registry. На сервере:

```bash
cd /opt/applytrack
sudo sed -i 's|API_IMAGE=.*|API_IMAGE=ghcr.io/MeldanLess/rest-api:v1.0.0|' deploy/env.production
sudo systemctl reload applytrack
```

Миграции выполнятся автоматически при следующем старте. **Сначала сделайте
резервную копию** — миграция по умолчанию необратима, а `alembic downgrade` — это
обещание, а не гарантия.

## 8. Откат

```bash
sudo sed -i 's|API_IMAGE=.*|API_IMAGE=ghcr.io/MeldanLess/rest-api:v0.9.0|' deploy/env.production
sudo systemctl reload applytrack
```

Образ неизменяем, поэтому откат — это указание на предыдущий тег. Если миграция
уже применилась, откатывайте и схему:

```bash
docker compose -f docker-compose.prod.yml run --rm api alembic downgrade -1
```

---

## Разбор неполадок

| Симптом | Вероятная причина | Что проверить |
|---|---|---|
| `/health` отдаёт `database: down` | API стартовал раньше, чем база была готова | `docker compose -f docker-compose.prod.yml ps`; этому должен мешать `depends_on: condition: service_healthy` |
| `502 Bad Gateway` от nginx | API не слушает `127.0.0.1:8000` | `journalctl -u applytrack -n 50` |
| `422` на каждый запрос | Клиент присылает тело там, где эндпоинт его не ждёт | `curl -v` к эндпоинту; в документации FastAPI показана ожидаемая форма |
| `401` при верном пароле | Токен подписан другим `SECRET_KEY` | `docker compose -f docker-compose.prod.yml logs api` — смена `SECRET_KEY` обесценивает каждый выданный токен |
| API перезапускается по кругу | База переполнена или ключ остался дефолтным | `docker compose -f docker-compose.prod.yml logs api` |

## Почему именно такая схема

- **Docker на сервере, а не PaaS.** Смысл проекта — показать, что API умеет
  работать в настоящем месте. «Развёрнуто за nginx на VPS с юнитом systemd» —
  фраза, которую я готов защитить на собеседовании; «развёрнуто на Render» —
  фраза про кнопку.
- **База не публикуется на хост.** С ней общается только контейнер API. База,
  доступная из интернета, — это база, до которой дотянутся.
- **nginx как системный сервис, а не контейнер.** certbot обновляет
  сертификаты, переписывая конфигурацию nginx и перезагружая его. Если делать
  это внутри контейнера, получается перезапуск контейнера и ещё том под
  сертификаты.
- **Один `Dockerfile` везде.** Образ, прошедший CI, — это побайтово тот же
  образ, что работает в бою.
