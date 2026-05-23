# Homework 7: CI/CD, Testing & Observability

Система для ДЗ7 построена на базе пайплайна аналитики онлайн-кинотеатра.

- `producer-service` принимает HTTP-запросы, валидирует события и публикует их в Kafka.
- `aggregation-service` читает уже загруженные данные, считает агрегаты и сохраняет итоговые метрики в PostgreSQL.
- `Kafka + Schema Registry + ClickHouse + PostgreSQL + MinIO` образуют тестовое окружение.
- `Prometheus + Grafana + Alertmanager` обеспечивают мониторинг, визуализацию и алерты.
- `k6 + pytest + GitHub Actions` обеспечивают автоматическое тестирование и CI/CD.

Все компоненты поднимаются одной командой:

```bash
docker compose up --build
```

## Что реализовано по требованиям

### Блок 1–4

- CI pipeline в [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)
- build, unit tests, integration tests, E2E tests, load tests
- `/metrics` на каждом сервисе
- базовые Prometheus-метрики:
  - `http_requests_total{service,method,endpoint,status}`
  - `http_request_errors_total{service,method,endpoint,error_type}`
  - `http_request_duration_seconds{service,method,endpoint}`

### Блок 5–7

- Grafana provisioning для datasource и dashboards
- dashboard сервисов: `infra/grafana/dashboards/services-observability.json`
- dashboard инфраструктуры: `infra/grafana/dashboards/infrastructure-overview.json`
- нагрузочный тест `load-tests/movie_events.js`
- результаты нагрузки и метрик складываются в `artifacts/`

### Блок 8–10

- в CI после нагрузки выполняется проверка SLI через Prometheus API
- alert rules как код: `infra/prometheus/alerts.yml`
- Alertmanager поднимается в compose
- SLI/SLO и пороги отказа документированы ниже

## Архитектура

```text
Client -> producer-service -> Kafka -> ClickHouse -> aggregation-service -> PostgreSQL / MinIO
                                   |
                                   +-> Prometheus <- Grafana / Alertmanager
```

## Основные адреса

- `Producer API`: `http://localhost:8000`
- `Aggregation API`: `http://localhost:8001`
- `Prometheus`: `http://localhost:9090`
- `Grafana`: `http://localhost:3000` (`admin` / `admin`)
- `Alertmanager`: `http://localhost:9093`
- `Schema Registry`: `http://localhost:8081`
- `ClickHouse`: `http://localhost:8123`
- `MinIO Console`: `http://localhost:9001`

## Тестовые сценарии

### Unit tests

```bash
python -m pip install -r producer-service/requirements.txt
PYTHONPATH=producer-service pytest -q producer-service/tests

python -m pip install -r aggregation-service/requirements.txt
PYTHONPATH=aggregation-service pytest -q aggregation-service/tests
```

### Integration test

Проверяет полный путь `HTTP -> Kafka -> ClickHouse`.

```bash
docker compose --profile test run --rm tests pytest -q test_integration.py
```

### E2E test

Проверяет путь `HTTP -> Kafka -> ClickHouse -> aggregation-service -> PostgreSQL`.

Что проверяется:

- HTTP статус и тело ответа `POST /events`
- HTTP статус и тело ответа `POST /aggregate`
- наличие raw event в ClickHouse
- наличие рассчитанных метрик в PostgreSQL

Запуск:

```bash
docker compose --profile test run --rm tests pytest -q test_e2e.py
```

### Нагрузочный тест

Тест создаёт постоянную нагрузку минимум `12 VU` в течение `35s`.

```bash
docker compose --profile load run --rm k6
```

Thresholds:

- `http_req_failed < 1%`
- `producer p95 < 500ms`
- `checks > 99%`

Результат сохраняется в `artifacts/load-summary.json`.

### Проверка метрик и SLI

После нагрузки проверяется Prometheus API:

```bash
docker compose --profile test run --rm tests python validate_metrics.py
```

Результат сохраняется в `artifacts/metrics-validation.json`.

## SLI / SLO / пороги отказа

### 1. API availability

- SLI: доля успешных запросов `2xx` к `producer-service`
- PromQL:

```promql
sum(rate(http_requests_total{service="producer-service",status=~"2..",endpoint!="/metrics"}[5m]))
/
sum(rate(http_requests_total{service="producer-service",endpoint!="/metrics"}[5m]))
```

- SLO: `> 99.5%`
- Порог отказа: `< 95%`

### 2. API latency p95

- SLI: `p95` latency для `producer-service`
- PromQL:

```promql
histogram_quantile(
  0.95,
  sum by (le) (
    rate(http_request_duration_seconds_bucket{service="producer-service",endpoint!="/metrics"}[5m])
  )
)
```

- SLO: `< 500ms`
- Порог отказа: `> 1000ms`

### 3. Event processing lag

- SLI: lag consumer group `clickhouse-movie-events`
- PromQL:

```promql
kafka_consumergroup_lag_sum{consumergroup="clickhouse-movie-events"}
```

- SLO: `< 100`
- Порог отказа: `> 1000`

Первые два SLI используются в CI через `tests/validate_metrics.py`.

## Alert rules

Файл: `infra/prometheus/alerts.yml`

Реализованы алерты:

- `ServiceDown`
- `HighErrorRate`
- `HighLatencyP95`

### Как показать firing на защите

`ServiceDown`:

```bash
docker compose stop producer-service
```

Через ~1 минуту алерт появится в Alertmanager UI.

`HighErrorRate`:

```bash
for i in {1..80}; do
  curl -s -o /dev/null -X POST http://localhost:8000/events \
    -H 'Content-Type: application/json' \
    -d '{"user_id":"","movie_id":"","event_type":"VIEW_FINISHED","device_type":"DESKTOP","session_id":"","progress_seconds":1}'
done
```

Это создаст поток `4xx`-ошибок и поднимет error rate выше порога.

## Grafana dashboards

### 1. Service Observability

Файл: `infra/grafana/dashboards/services-observability.json`

Секции:

- `producer-service`
- `aggregation-service`

Панели:

- throughput
- error rate
- latency p50/p95/p99
- распределение по статусам

### 2. Infrastructure Overview

Файл: `infra/grafana/dashboards/infrastructure-overview.json`

Панели:

- healthy targets
- Kafka brokers / partitions / consumer lag
- PostgreSQL connections / commits
- scrape target availability
- cache hit ratio / offset growth

Этот dashboard отвечает на вопрос, где узкое место: в запросах, в Kafka lag или в PostgreSQL.

## Полезные проверки вручную

### Проверка метрик сервисов

```bash
curl http://localhost:8000/metrics | head
curl http://localhost:8001/metrics | head
```

### Проверка Prometheus targets

```bash
curl http://localhost:9090/api/v1/targets
```

### Проверка Alertmanager

```bash
curl http://localhost:9093/api/v2/alerts
```

### Проверка данных в ClickHouse

```bash
curl -u analytics:analytics \
  'http://localhost:8123/?query=SELECT%20event_id,user_id,movie_id,event_type,event_date%20FROM%20movie_analytics.movie_events%20ORDER%20BY%20timestamp%20DESC%20LIMIT%2010'
```

### Проверка данных в PostgreSQL

```bash
docker compose exec postgres psql -U analytics -d movie_analytics \
  -c "SELECT metric_date, metric_name, metric_value FROM daily_metrics ORDER BY computed_at DESC LIMIT 20;"
```

## CI pipeline

Файл: [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)

Последовательность:

1. `docker compose build`
2. unit tests для каждого сервиса
3. `docker compose up -d`
4. integration tests
5. E2E tests
6. load tests
7. проверка метрик и SLI через Prometheus API
8. выгрузка артефактов:
   - `artifacts/load-summary.json`
   - `artifacts/metrics-validation.json`
   - `artifacts/compose.log`
   - `artifacts/prometheus-rules.json`
   - `artifacts/alertmanager-alerts.json`

## Что показывать на защите за 20 минут

1. `docker compose up --build` и логи старта.
2. Открыть GitHub Actions и показать успешный `dz7-ci`.
3. Запустить:

```bash
docker compose --profile test run --rm tests pytest -q test_integration.py test_e2e.py
docker compose --profile load run --rm k6
docker compose --profile test run --rm tests python validate_metrics.py
```

4. Открыть Prometheus, Grafana и Alertmanager.
5. Показать `/metrics` у обоих сервисов.
6. Открыть `artifacts/` и показать результаты нагрузки и проверки метрик.

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
