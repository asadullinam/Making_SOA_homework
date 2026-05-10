# Homework 6: Smart Warehouse on Kafka + Cassandra

Автономный стенд для event-driven управления складом:

- `wms-service` публикует складские события в Kafka topic `warehouse-events`.
- `Schema Registry` хранит Avro-схемы `warehouse-events-value` и демонстрирует schema evolution V1 -> V2.
- `consumer-service` читает события в consumer group `warehouse-state-consumer`, применяет stateful-логику и обновляет Cassandra.
- `Cassandra` развернута кластером из 3 нод.
- Проблемные события отправляются в `warehouse-events-dlq`.
- `Prometheus` и `Grafana` собирают метрики consumer'а.

## Запуск

```bash
docker compose up --build
```

Сервисы после старта:

- WMS API: `http://localhost:8000`
- Swagger UI: `http://localhost:8000/docs`
- Consumer health/metrics: `http://localhost:8001/health`, `http://localhost:8001/metrics`
- Schema Registry: `http://localhost:8081`
- Cassandra: `localhost:9042`
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000` (`admin` / `admin`)

## Как проверять через Swagger

1. Откройте `http://localhost:8000/docs`
2. Используйте `POST /events`
3. В `Request body` выбирайте готовые `Examples`
4. Для schema evolution:
   - `v=1` для V1 без `supplier_id`
   - `v=2` для V2 с `supplier_id`
5. После отправки события проверяйте состояние через `cqlsh`, Kafka DLQ, Prometheus и Grafana по командам ниже

## Что реализовано по баллам

### 1-4 балла

- Consumer читает `warehouse-events` в группе `warehouse-state-consumer`.
- Offset commit происходит только после успешной записи в Cassandra или успешной отправки в DLQ.
- Логи содержат `event_id`, `event_type`, `partition`, `offset`.
- Схема Cassandra спроектирована под запросы без `JOIN`.
- Состояние склада хранится в денормализованных таблицах.
- Идемпотентность реализована через таблицу `processed_events`.

### 5-7 баллов

- Одно событие обновляет все связанные таблицы через `LOGGED BATCH`.
- Старые события игнорируются по `event_timestamp`.
- Ошибочные события улетают в `warehouse-events-dlq` с причиной ошибки и Kafka metadata.

### 8-10 баллов

- Cassandra работает кластером из `cassandra-1`, `cassandra-2`, `cassandra-3`.
- Keyspace создается с `NetworkTopologyStrategy` и `replication_factor = 3`.
- Записи идут с `QUORUM`, чтения тоже с `QUORUM`.
- Есть `/metrics`, `/health`, Prometheus rules и Grafana dashboard.
- Зарегистрированы две версии Avro-схемы: V1 и V2 с полем `supplier_id`.

## Модель данных Cassandra

### Таблица `inventory_by_product_zone`

Поддерживает запрос остатка товара в конкретной зоне:

```sql
SELECT * FROM warehouse.inventory_by_product_zone
WHERE product_id = 'SKU-001' AND zone_id = 'ZONE-A';
```

- `partition key`: `product_id`
- `clustering key`: `zone_id`
- Причина: типичный запрос начинается с товара и раскрывает его размещение по зонам.

### Таблица `inventory_by_product`

Поддерживает агрегированный остаток по товару:

```sql
SELECT * FROM warehouse.inventory_by_product
WHERE product_id = 'SKU-001';
```

- `partition key`: `product_id`
- Одна строка на товар, быстрый доступ к total available / reserved.

### Таблица `inventory_by_zone`

Поддерживает список товаров внутри зоны:

```sql
SELECT * FROM warehouse.inventory_by_zone
WHERE zone_id = 'ZONE-A';
```

- `partition key`: `zone_id`
- `clustering key`: `product_id`
- Причина: для оператора склада естественно открывать содержимое конкретной зоны.

### Дополнительные таблицы

- `processed_events` - защита от дублей по `event_id`
- `orders_by_id` - состояние заказов
- `event_audit_by_day` - история обработки для аудита

## Почему выбран `QUORUM`

- Для записей `QUORUM` нужен, чтобы одна убитая нода не приводила к потере подтвержденных обновлений.
- Для чтений выбран тоже `QUORUM`, потому что в этом задании важнее консистентность состояния склада, чем минимальная latency.
- Trade-off: `ONE` быстрее, но может вернуть устаревшее состояние после частичного отказа.

## Schema Evolution

Используется `BACKWARD` compatibility для subject `warehouse-events-value`.

### V1

Схема без поля `supplier_id`.

### V2

В `ProductReceived`-совместимом общем событии добавлено поле:

```json
{"name": "supplier_id", "type": ["null", "string"], "default": null}
```

### Как добавлять новую версию

1. Обновить `.avsc`, добавив только backward-compatible поля.
2. Для новых nullable полей задать `default`.
3. Зарегистрировать схему в Schema Registry.
4. Обновить consumer-логику для чтения старой и новой версии.
5. Добавить колонку в Cassandra и обновить batch-запись.
6. Проверить, что V1 и V2 сообщения в одном topic обрабатываются без ошибок.

## Основные HTTP сценарии

### PRODUCT_RECEIVED V2

```bash
curl -X POST http://localhost:8000/events?v=2 \
  -H 'Content-Type: application/json' \
  -d '{
    "event_id": "evt-001",
    "event_type": "PRODUCT_RECEIVED",
    "product_id": "SKU-001",
    "zone_id": "ZONE-A",
    "quantity": 100,
    "supplier_id": "SUP-001",
    "event_timestamp": "2026-05-10T10:00:00Z"
  }'
```

### PRODUCT_RECEIVED V1

```bash
curl -X POST http://localhost:8000/events?v=1 \
  -H 'Content-Type: application/json' \
  -d '{
    "event_id": "evt-v1-001",
    "event_type": "PRODUCT_RECEIVED",
    "product_id": "SKU-V1",
    "zone_id": "ZONE-A",
    "quantity": 25,
    "event_timestamp": "2026-05-10T10:01:00Z"
  }'
```

### ORDER_CREATED

```bash
curl -X POST http://localhost:8000/events \
  -H 'Content-Type: application/json' \
  -d '{
    "event_id": "evt-order-1",
    "event_type": "ORDER_CREATED",
    "order_id": "ORD-001",
    "event_timestamp": "2026-05-10T10:05:00Z",
    "order_lines": [
      {"product_id": "SKU-001", "zone_id": "ZONE-A", "quantity": 15}
    ]
  }'
```

### Невалидное событие для DLQ

```bash
curl -X POST http://localhost:8000/events \
  -H 'Content-Type: application/json' \
  -d '{
    "event_id": "evt-bad-1",
    "event_type": "PRODUCT_SHIPPED",
    "product_id": "SKU-001",
    "zone_id": "ZONE-A",
    "quantity": -5,
    "event_timestamp": "2026-05-10T10:06:00Z"
  }'
```

## Пошаговые действия для 8 сценариев

Ниже перечислено, какой пункт задания мы проверяем, что именно мы отправляем через Swagger и какими командами подтверждаем результат.

### Сценарий 1. Базовый цикл склада

Что мы проверяем:

- consumer читает события из Kafka
- состояние склада меняется в Cassandra
- логика операций соответствует предметной области

Что мы делаем:

1. В Swagger отправляем `PRODUCT_RECEIVED`:

```json
{
  "event_id": "s1-001",
  "event_type": "PRODUCT_RECEIVED",
  "product_id": "SKU-001",
  "zone_id": "ZONE-A",
  "quantity": 100,
  "supplier_id": "SUP-001",
  "event_timestamp": "2026-05-10T10:00:00Z"
}
```

2. В Swagger отправляем `PRODUCT_RESERVED`:

```json
{
  "event_id": "s1-002",
  "event_type": "PRODUCT_RESERVED",
  "product_id": "SKU-001",
  "zone_id": "ZONE-A",
  "quantity": 30,
  "event_timestamp": "2026-05-10T10:01:00Z"
}
```

3. В Swagger отправляем `PRODUCT_MOVED`:

```json
{
  "event_id": "s1-003",
  "event_type": "PRODUCT_MOVED",
  "product_id": "SKU-001",
  "from_zone_id": "ZONE-A",
  "to_zone_id": "ZONE-B",
  "quantity": 20,
  "event_timestamp": "2026-05-10T10:02:00Z"
}
```

4. В Swagger отправляем `PRODUCT_SHIPPED`:

```json
{
  "event_id": "s1-004",
  "event_type": "PRODUCT_SHIPPED",
  "product_id": "SKU-001",
  "zone_id": "ZONE-A",
  "quantity": 10,
  "event_timestamp": "2026-05-10T10:03:00Z"
}
```

5. В Swagger отправляем `ORDER_CREATED`:

```json
{
  "event_id": "s1-005",
  "event_type": "ORDER_CREATED",
  "order_id": "ORD-001",
  "event_timestamp": "2026-05-10T10:04:00Z",
  "order_lines": [
    {
      "product_id": "SKU-001",
      "zone_id": "ZONE-A",
      "quantity": 15
    }
  ]
}
```

6. В Swagger отправляем `ORDER_COMPLETED`:

```json
{
  "event_id": "s1-006",
  "event_type": "ORDER_COMPLETED",
  "order_id": "ORD-001",
  "event_timestamp": "2026-05-10T10:05:00Z"
}
```

Как мы проверяем:

После `PRODUCT_RECEIVED`:

```bash
docker compose exec -T cassandra-1 cqlsh -e "
SELECT product_id, zone_id, available_quantity, reserved_quantity
FROM warehouse.inventory_by_product_zone
WHERE product_id = 'SKU-001' AND zone_id = 'ZONE-A';
"
```

Ожидаем `available_quantity = 100`.

После `PRODUCT_RESERVED`:

```bash
docker compose exec -T cassandra-1 cqlsh -e "
SELECT product_id, zone_id, available_quantity, reserved_quantity
FROM warehouse.inventory_by_product_zone
WHERE product_id = 'SKU-001' AND zone_id = 'ZONE-A';
"
```

Ожидаем `available_quantity = 70`, `reserved_quantity = 30`.

После `PRODUCT_MOVED`:

```bash
docker compose exec -T cassandra-1 cqlsh -e "
SELECT product_id, zone_id, available_quantity, reserved_quantity
FROM warehouse.inventory_by_product_zone
WHERE product_id = 'SKU-001' AND zone_id = 'ZONE-A';
"
```

```bash
docker compose exec -T cassandra-1 cqlsh -e "
SELECT product_id, zone_id, available_quantity, reserved_quantity
FROM warehouse.inventory_by_product_zone
WHERE product_id = 'SKU-001' AND zone_id = 'ZONE-B';
"
```

Ожидаем:

- `ZONE-A available=50 reserved=30`
- `ZONE-B available=20 reserved=0`

После `PRODUCT_SHIPPED`:

```bash
docker compose exec -T cassandra-1 cqlsh -e "
SELECT product_id, zone_id, available_quantity, reserved_quantity
FROM warehouse.inventory_by_product_zone
WHERE product_id = 'SKU-001' AND zone_id = 'ZONE-A';
"
```

Ожидаем `ZONE-A available=40 reserved=30`.

После `ORDER_CREATED`:

```bash
docker compose exec -T cassandra-1 cqlsh -e "
SELECT order_id, status, items_json
FROM warehouse.orders_by_id
WHERE order_id = 'ORD-001';
"
```

```bash
docker compose exec -T cassandra-1 cqlsh -e "
SELECT product_id, zone_id, available_quantity, reserved_quantity
FROM warehouse.inventory_by_product_zone
WHERE product_id = 'SKU-001' AND zone_id = 'ZONE-A';
"
```

Ожидаем:

- заказ `CREATED`
- `ZONE-A available=25 reserved=45`

После `ORDER_COMPLETED`:

```bash
docker compose exec -T cassandra-1 cqlsh -e "
SELECT order_id, status
FROM warehouse.orders_by_id
WHERE order_id = 'ORD-001';
"
```

```bash
docker compose exec -T cassandra-1 cqlsh -e "
SELECT product_id, zone_id, available_quantity, reserved_quantity
FROM warehouse.inventory_by_product_zone
WHERE product_id = 'SKU-001' AND zone_id = 'ZONE-A';
"
```

Ожидаем:

- заказ `COMPLETED`
- `ZONE-A available=25 reserved=30`

### Сценарий 2. Идемпотентность

Что мы проверяем:

- повторная доставка одного и того же `event_id` не ломает состояние

Что мы делаем:

1. В Swagger отправляем событие:

```json
{
  "event_id": "dup-001",
  "event_type": "PRODUCT_RECEIVED",
  "product_id": "SKU-002",
  "zone_id": "ZONE-A",
  "quantity": 50,
  "event_timestamp": "2026-05-10T11:00:00Z"
}
```

2. Повторно отправляем тот же самый body с тем же `event_id`:

```json
{
  "event_id": "dup-001",
  "event_type": "PRODUCT_RECEIVED",
  "product_id": "SKU-002",
  "zone_id": "ZONE-A",
  "quantity": 50,
  "event_timestamp": "2026-05-10T11:00:00Z"
}
```

Как мы проверяем:

```bash
docker compose exec -T cassandra-1 cqlsh -e "
SELECT product_id, zone_id, available_quantity, reserved_quantity
FROM warehouse.inventory_by_product_zone
WHERE product_id = 'SKU-002' AND zone_id = 'ZONE-A';
"
```

```bash
docker compose logs --tail=50 consumer-service
```

Ожидаем:

- `available_quantity = 50`, а не `100`
- в логах второе событие имеет статус `DUPLICATE`

### Сценарий 3. Консистентность таблиц

Что мы проверяем:

- одно событие консистентно обновляет все денормализованные таблицы

Что мы делаем:

1. В Swagger отправляем событие:

```json
{
  "event_id": "cons-001",
  "event_type": "PRODUCT_RECEIVED",
  "product_id": "SKU-003",
  "zone_id": "ZONE-A",
  "quantity": 100,
  "supplier_id": "SUP-003",
  "event_timestamp": "2026-05-10T12:00:00Z"
}
```

Как мы проверяем:

```bash
docker compose exec -T cassandra-1 cqlsh -e "
SELECT product_id, zone_id, available_quantity, reserved_quantity
FROM warehouse.inventory_by_product_zone
WHERE product_id = 'SKU-003' AND zone_id = 'ZONE-A';
"
```

```bash
docker compose exec -T cassandra-1 cqlsh -e "
SELECT product_id, total_available_quantity, total_reserved_quantity
FROM warehouse.inventory_by_product
WHERE product_id = 'SKU-003';
"
```

```bash
docker compose exec -T cassandra-1 cqlsh -e "
SELECT zone_id, product_id, available_quantity, reserved_quantity
FROM warehouse.inventory_by_zone
WHERE zone_id = 'ZONE-A';
"
```

Ожидаем, что:

- в `inventory_by_product_zone` для `SKU-003` в `ZONE-A` лежит `available=100`
- в `inventory_by_product` для `SKU-003` лежит `total_available=100`
- в `inventory_by_zone` зона `ZONE-A` содержит `SKU-003` с `available=100`

### Сценарий 4. События вне порядка

Что мы проверяем:

- старое событие, пришедшее позже, не затирает новое состояние

Что мы делаем:

1. В Swagger отправляем первое событие:

```json
{
  "event_id": "ooo-001",
  "event_type": "PRODUCT_RECEIVED",
  "product_id": "SKU-004",
  "zone_id": "ZONE-A",
  "quantity": 100,
  "event_timestamp": "2026-05-10T12:00:00Z"
}
```

2. В Swagger отправляем второе, более новое событие:

```json
{
  "event_id": "ooo-002",
  "event_type": "PRODUCT_SHIPPED",
  "product_id": "SKU-004",
  "zone_id": "ZONE-A",
  "quantity": 20,
  "event_timestamp": "2026-05-10T12:05:00Z"
}
```

3. В Swagger отправляем старое событие, которое приходит позже:

```json
{
  "event_id": "ooo-003",
  "event_type": "PRODUCT_RECEIVED",
  "product_id": "SKU-004",
  "zone_id": "ZONE-A",
  "quantity": 50,
  "event_timestamp": "2026-05-10T12:02:00Z"
}
```

Как мы проверяем:

```bash
docker compose exec -T cassandra-1 cqlsh -e "
SELECT product_id, zone_id, available_quantity, reserved_quantity
FROM warehouse.inventory_by_product_zone
WHERE product_id = 'SKU-004' AND zone_id = 'ZONE-A';
"
```

```bash
docker compose exec -T cassandra-1 cqlsh -e "
SELECT event_id, event_type, status, error_reason
FROM warehouse.processed_events
WHERE event_id IN ('ooo-001', 'ooo-002', 'ooo-003');
"
```

Ожидаем:

- финальный остаток `available=80`
- для `ooo-003` в `processed_events` статус `STALE`

### Сценарий 5. Dead Letter Queue

Что мы проверяем:

- невалидное событие не блокирует consumer и уходит в DLQ

Что мы делаем:

1. В Swagger отправляем невалидное событие:

```json
{
  "event_id": "dlq-001",
  "event_type": "PRODUCT_SHIPPED",
  "product_id": "SKU-005",
  "zone_id": "ZONE-A",
  "quantity": -5,
  "event_timestamp": "2026-05-10T13:00:00Z"
}
```

2. Затем отправляем валидное событие:

```json
{
  "event_id": "dlq-002",
  "event_type": "PRODUCT_RECEIVED",
  "product_id": "SKU-005",
  "zone_id": "ZONE-A",
  "quantity": 10,
  "event_timestamp": "2026-05-10T13:01:00Z"
}
```

Как мы проверяем:

```bash
docker compose logs --tail=80 consumer-service
```

```bash
docker compose exec -T kafka-1 kafka-console-consumer \
  --bootstrap-server kafka-1:9092 \
  --topic warehouse-events-dlq \
  --from-beginning \
  --timeout-ms 4000
```

```bash
docker compose exec -T cassandra-1 cqlsh -e "
SELECT product_id, zone_id, available_quantity, reserved_quantity
FROM warehouse.inventory_by_product_zone
WHERE product_id = 'SKU-005' AND zone_id = 'ZONE-A';
"
```

Ожидаем:

- в логах consumer остаётся жив
- в DLQ есть JSON с `error_reason` и Kafka metadata
- второе валидное событие применилось, `available=10`

### Сценарий 6. Cassandra cluster и отказоустойчивость

Что мы проверяем:

- Cassandra-кластер из 3 нод продолжает обслуживать запись при падении одной ноды

Что мы делаем:

1. Смотрим кластер:

```bash
docker compose exec cassandra-1 nodetool status
```

2. Останавливаем одну ноду:

```bash
docker stop dz6-cassandra-2
```

3. В Swagger отправляем событие:

```json
{
  "event_id": "cl-001",
  "event_type": "PRODUCT_RECEIVED",
  "product_id": "SKU-006",
  "zone_id": "ZONE-A",
  "quantity": 200,
  "supplier_id": "SUP-006",
  "event_timestamp": "2026-05-10T14:00:00Z"
}
```

4. Проверяем запись:

```bash
docker compose exec -T cassandra-1 cqlsh -e "
SELECT product_id, zone_id, available_quantity, reserved_quantity, supplier_id
FROM warehouse.inventory_by_product_zone
WHERE product_id = 'SKU-006' AND zone_id = 'ZONE-A';
"
```

5. Поднимаем ноду обратно:

```bash
docker start dz6-cassandra-2
```

6. Снова смотрим кластер:

```bash
docker compose exec cassandra-1 nodetool status
```

Ожидаем:

- при одной упавшей ноде событие всё равно записывается
- после возврата ноды статус снова `UN` на всех трёх нодах

### Сценарий 7. Monitoring

Что мы проверяем:

- consumer публикует health и Prometheus-метрики, а Prometheus/Grafana их видят

Что мы делаем:

1. В Swagger отправляем событие:

```json
{
  "event_id": "mon-001",
  "event_type": "PRODUCT_RECEIVED",
  "product_id": "SKU-007",
  "zone_id": "ZONE-A",
  "quantity": 20,
  "event_timestamp": "2026-05-10T15:00:00Z"
}
```

Как мы проверяем:

```bash
curl -i http://localhost:8001/health
```

```bash
curl -s http://localhost:8001/metrics | rg 'consumer_lag|events_processed_total|event_processing_duration_seconds|cassandra_write_errors_total'
```

```bash
curl -s http://localhost:9090/-/healthy
```

```bash
curl -s http://localhost:3000/api/health
```

Ожидаем:

- `/health` возвращает `200 OK`
- в `/metrics` видны все требуемые метрики
- Prometheus healthy
- Grafana healthy

### Сценарий 8. Schema Evolution

Что мы проверяем:

- consumer одновременно обрабатывает V1 и V2 одного события

Что мы делаем:

1. В Swagger отправляем V1-событие с query-параметром `v=1`:

```json
{
  "event_id": "sch-001",
  "event_type": "PRODUCT_RECEIVED",
  "product_id": "SKU-V1",
  "zone_id": "ZONE-A",
  "quantity": 25,
  "event_timestamp": "2026-05-10T16:00:00Z"
}
```

2. В Swagger отправляем V2-событие с query-параметром `v=2`:

```json
{
  "event_id": "sch-002",
  "event_type": "PRODUCT_RECEIVED",
  "product_id": "SKU-V2",
  "zone_id": "ZONE-A",
  "quantity": 25,
  "supplier_id": "SUP-V2",
  "event_timestamp": "2026-05-10T16:01:00Z"
}
```

Как мы проверяем:

```bash
docker compose exec -T cassandra-1 cqlsh -e "
SELECT product_id, zone_id, available_quantity, supplier_id
FROM warehouse.inventory_by_product_zone
WHERE product_id = 'SKU-V1' AND zone_id = 'ZONE-A';
"
```

```bash
docker compose exec -T cassandra-1 cqlsh -e "
SELECT product_id, zone_id, available_quantity, supplier_id
FROM warehouse.inventory_by_product_zone
WHERE product_id = 'SKU-V2' AND zone_id = 'ZONE-A';
"
```

```bash
curl -s http://localhost:8081/subjects/warehouse-events-value/versions
```

Ожидаем:

- для `SKU-V1` поле `supplier_id = null`
- для `SKU-V2` поле `supplier_id = 'SUP-V2'`
- в Schema Registry зарегистрированы обе версии

## Проверка Cassandra

### Статус кластера

```bash
docker compose exec cassandra-1 nodetool status
```

### Остатки по товару и зоне

```bash
docker compose exec cassandra-1 cqlsh -e "
SELECT product_id, zone_id, available_quantity, reserved_quantity, supplier_id
FROM warehouse.inventory_by_product_zone
WHERE product_id = 'SKU-001' AND zone_id = 'ZONE-A';
"
```

### Агрегат по товару

```bash
docker compose exec cassandra-1 cqlsh -e "
SELECT product_id, total_available_quantity, total_reserved_quantity
FROM warehouse.inventory_by_product
WHERE product_id = 'SKU-001';
"
```

### Товары в зоне

```bash
docker compose exec cassandra-1 cqlsh -e "
SELECT zone_id, product_id, available_quantity, reserved_quantity
FROM warehouse.inventory_by_zone
WHERE zone_id = 'ZONE-A';
"
```

### История обработки

```bash
docker compose exec cassandra-1 cqlsh -e "
SELECT event_day, processed_at, event_id, event_type, status
FROM warehouse.event_audit_by_day
LIMIT 20;
"
```

## Проверка DLQ

```bash
docker compose exec kafka-1 kafka-console-consumer \
  --bootstrap-server kafka-1:9092 \
  --topic warehouse-events-dlq \
  --from-beginning
```

## Мониторинг

- `/health` возвращает `200`, когда consumer подключен к Kafka и Cassandra.
- `/health` возвращает `503`, если одно из соединений потеряно.
- `/metrics` публикует:
  - `consumer_lag`
  - `events_processed_total`
  - `event_processing_duration_seconds`
  - `cassandra_write_errors_total`

Grafana dashboard `Warehouse Monitoring` содержит панели:

- Consumer Lag by Partition
- Events Processed / sec
- Cassandra Write Errors

## Демонстрация отказоустойчивости Cassandra

1. Поднять систему: `docker compose up --build`
2. Проверить кластер: `docker compose exec cassandra-1 nodetool status`
3. Остановить одну ноду: `docker stop dz6-cassandra-2`
4. Отправить новое валидное событие через `wms-service`
5. Убедиться, что consumer продолжает обновлять состояние с `QUORUM`
6. Вернуть ноду: `docker start dz6-cassandra-2`
7. Повторно проверить `nodetool status`
