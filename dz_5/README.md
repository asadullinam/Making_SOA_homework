# Homework 5: Online Cinema Analytics Pipeline

Полностью автономный стенд для стриминга событий онлайн-кинотеатра:

- `producer-service` принимает JSON по HTTP и публикует Avro-события в Kafka.
- `Schema Registry` хранит версионированную схему `movie-events-value`.
- `ClickHouse` принимает данные через `Kafka Engine` и хранит raw + materialized aggregates.
- `aggregation-service` по расписанию или вручную считает бизнес-метрики, автоматически применяет Alembic-миграции PostgreSQL, делает upsert и экспорт в MinIO.
- `Grafana` показывает готовый dashboard поверх агрегатов из ClickHouse.

## Запуск

```bash
docker compose up --build
```

Сервисы после старта:

- Producer API: `http://localhost:8000`
- Aggregation API: `http://localhost:8001`
- Schema Registry: `http://localhost:8081`
- ClickHouse HTTP: `http://localhost:8123`
- Grafana: `http://localhost:3000` (`admin` / `admin`)
- MinIO Console: `http://localhost:9001` (`minio` / `miniosecret`)

## Интеграционный тест

```bash
docker compose --profile test run --rm tests
```

## Ручной пересчёт и экспорт

```bash
curl -X POST "http://localhost:8001/aggregate?target_date=2026-04-15"
curl -X POST "http://localhost:8001/export?target_date=2026-04-15"
```

## Что где лежит и как проверять

### Основные адреса

- `Producer API`: `http://localhost:8000`
- `Aggregation API`: `http://localhost:8001`
- `Schema Registry`: `http://localhost:8081`
- `ClickHouse HTTP`: `http://localhost:8123`
- `Grafana`: `http://localhost:3000`
- `MinIO Console`: `http://localhost:9001`

### Где что лежит в проекте

- Инфраструктура и все сервисы в одном compose: `docker-compose.yml`
- Avro-схема события: `schemas/movie-event.avsc`
- Kafka init-скрипт с созданием topic и регистрацией схемы: `infra/kafka/init-topics-and-schema.sh`
- ClickHouse init SQL: `infra/clickhouse/init/01_init.sql`
- Grafana datasource и dashboard provisioning: `infra/grafana/provisioning`
- Grafana dashboard JSON: `infra/grafana/dashboards/movie-analytics.json`
- MinIO init-скрипт: `infra/minio/init-minio.sh`
- Producer service: `producer-service/app`
- Aggregation service: `aggregation-service/app`
- Alembic-макеты и миграции PostgreSQL: `aggregation-service/alembic`
- Интеграционный тест pipeline: `tests/test_pipeline.py`

### Kafka и Schema Registry

- Topic: `movie-events`
- Subject в Schema Registry: `movie-events-value`
- Партиции: `3`
- Replication factor: `2`
- `min.insync.replicas=1`
- Ключ партиционирования: `user_id`

Проверка subject:

```bash
curl http://localhost:8081/subjects
curl http://localhost:8081/subjects/movie-events-value/versions/latest
```

Проверка topic:

```bash
docker compose exec kafka-1 kafka-topics --bootstrap-server kafka-1:9092 --describe --topic movie-events
```

### Producer

- HTTP endpoint приёма событий: `POST /events`
- Healthcheck: `GET /health`
- Генератор синтетических событий включён через `GENERATOR_ENABLED`

Публикация тестового события:

```bash
curl -X POST http://localhost:8000/events \
  -H 'Content-Type: application/json' \
  -d '{
    "user_id": "user-check-1",
    "movie_id": "movie-check-1",
    "event_type": "VIEW_FINISHED",
    "timestamp": "2026-04-21T12:00:00Z",
    "device_type": "DESKTOP",
    "session_id": "session-check-1",
    "progress_seconds": 3600
  }'
```

Логи producer:

```bash
docker compose logs -f producer-service
```

### ClickHouse

- Kafka ingestion table: `movie_analytics.movie_events_queue`
- Raw events table: `movie_analytics.movie_events`
- Агрегатные таблицы:
  - `movie_analytics.daily_dau`
  - `movie_analytics.daily_avg_watch_time`
  - `movie_analytics.daily_top_movies`
  - `movie_analytics.daily_conversion`
  - `movie_analytics.daily_retention`
  - `movie_analytics.device_distribution`
  - `movie_analytics.retention_cohorts`

Проверка raw-событий:

```bash
curl -u analytics:analytics \
  'http://localhost:8123/?query=SELECT%20event_id,user_id,movie_id,event_type,progress_seconds,timestamp%20FROM%20movie_analytics.movie_events%20ORDER%20BY%20timestamp%20DESC%20LIMIT%2010'
```

Проверка DAU:

```bash
curl -u analytics:analytics \
  'http://localhost:8123/?query=SELECT%20*%20FROM%20movie_analytics.daily_dau%20FINAL%20ORDER%20BY%20metric_date%20DESC'
```

Проверка conversion:

```bash
curl -u analytics:analytics \
  'http://localhost:8123/?query=SELECT%20*%20FROM%20movie_analytics.daily_conversion%20FINAL%20ORDER%20BY%20metric_date%20DESC'
```

Проверка retention cohorts:

```bash
curl -u analytics:analytics \
  'http://localhost:8123/?query=SELECT%20*%20FROM%20movie_analytics.retention_cohorts%20FINAL%20ORDER%20BY%20cohort_date%20DESC,lifecycle_day'
```

### Aggregation service

- Автоматический пересчёт запускается scheduler'ом
- Интервалы задаются через:
  - `AGGREGATION_SCHEDULE_MINUTES`
  - `EXPORT_SCHEDULE_MINUTES`
- Ручной пересчёт за дату: `POST /aggregate`
- Ручной экспорт за дату: `POST /export`

Пересчёт агрегатов:

```bash
curl -X POST "http://localhost:8001/aggregate?target_date=2026-04-21"
```

Экспорт в MinIO:

```bash
curl -X POST "http://localhost:8001/export?target_date=2026-04-21"
```

Логи aggregation-service:

```bash
docker compose logs -f aggregation-service
```

### PostgreSQL

- Готовые метрики хранятся в таблице `daily_metrics`
- Миграции применяются автоматически через `alembic upgrade head` при старте `aggregation-service`

Проверка миграций и метрик:

```bash
docker compose exec postgres psql -U analytics -d movie_analytics -c "\dt"
docker compose exec postgres psql -U analytics -d movie_analytics -c "select * from daily_metrics order by computed_at desc limit 20;"
```

### Grafana

- Datasource: ClickHouse
- Dashboard: `Movie Analytics`
- Панели:
  - `DAU`
  - `Conversion Rate`
  - `Average Watch Seconds`
  - `Retention Cohort Heatmap`

Проверка логов Grafana:

```bash
docker compose logs --tail=100 grafana
```

### MinIO / S3

- Bucket: `movie-analytics`
- Путь экспорта: `daily/YYYY-MM-DD/aggregates.csv`

Проверка списка файлов:

```bash
docker compose run --rm --entrypoint sh minio-init -c "
mc alias set local http://minio:9000 minio miniosecret &&
mc ls --recursive local/movie-analytics
"
```

Просмотр экспортированного CSV:

```bash
docker compose run --rm --entrypoint sh minio-init -c "
mc alias set local http://minio:9000 minio miniosecret &&
mc cat local/movie-analytics/daily/2026-04-21/aggregates.csv
"
```

### Полезные общие команды

Статус контейнеров:

```bash
docker compose ps
```

Интеграционный тест:

```bash
docker compose --profile test run --rm tests
```

Полная пересборка:

```bash
docker compose up --build
```

# накидать событий за 0..7 дней назад
```bash
for days_ago in {0..7}; do
  ts=$(date -u -v-"${days_ago}"d +"%Y-%m-%dT%H:%M:%SZ")
  for i in {1..50}; do
    sid="session-$(uuidgen)"
    uid="user-$((RANDOM%40))"
    mid="movie-$((RANDOM%20))"

    curl -s -X POST http://localhost:8000/events \
      -H 'Content-Type: application/json' \
      -d "{\"event_id\":\"$(uuidgen)\",\"user_id\":\"${uid}\",\"movie_id\":\"${mid}\",\"event_type\":\"VIEW_STARTED\",\"timestamp\":\"${ts}\",\"device_type\":\"DESKTOP\",\"session_id\":\"${sid}\",\"progress_seconds\":0}" >/dev/null

    curl -s -X POST http://localhost:8000/events \
      -H 'Content-Type: application/json' \
      -d "{\"event_id\":\"$(uuidgen)\",\"user_id\":\"${uid}\",\"movie_id\":\"${mid}\",\"event_type\":\"VIEW_FINISHED\",\"timestamp\":\"${ts}\",\"device_type\":\"DESKTOP\",\"session_id\":\"${sid}\",\"progress_seconds\":$((RANDOM%5400+300))}" >/dev/null
  done
done

for days_ago in {0..7}; do
  day=$(date -u -v-"${days_ago}"d +"%Y-%m-%d")
  curl -s -X POST "http://localhost:8001/aggregate?target_date=${day}" >/dev/null
done
```