# dz_3

Сервис бронирования авиабилетов из двух частей:

- `booking_service` - внешний HTTP API на `localhost:8080`
- `flight_service` - внутренний gRPC API на `localhost:50051`

Также в `docker-compose` поднимаются:

- `swagger_ui` - Swagger UI на `localhost:8081`
- `flight_db` - PostgreSQL на `localhost:5433`
- `booking_db` - PostgreSQL на `localhost:5434`
- `redis_master` - Redis на `localhost:6379`
- `redis_sentinel` - Sentinel на `localhost:26379`

## Запуск

Поднять весь проект:

```bash
docker compose -f docker-compose.yml up -d --build
```

Проверить контейнеры:

```bash
docker compose -f docker-compose.yml ps
```

## Куда ходить

- HTTP API: `http://localhost:8080`
- Swagger UI: `http://localhost:8081`
- gRPC API: `localhost:50051`

## Ручное тестирование HTTP

Swagger подключен к `booking_service`, поэтому кнопка `Try it out` шлет HTTP-запросы в `http://localhost:8080`.

Основной сценарий:

1. Открыть `GET /flights`
2. Указать:
   - `origin = SVO`
   - `destination = LED`
   - `date = 2026-04-01`
3. Нажать `Execute`
4. Скопировать `id` рейса из ответа
5. Открыть `GET /flights/{id}` и подставить этот `id`
6. Открыть `POST /bookings` и создать бронь
7. Открыть `GET /bookings/{id}` и проверить бронь
8. Открыть `GET /bookings?user_id=user-1`
9. Открыть `POST /bookings/{id}/cancel`

Пример тела для `POST /bookings`:

```json
{
  "user_id": "user-1",
  "flight_id": "UUID_РЕЙСА",
  "passenger_name": "Ivan Ivanov",
  "passenger_email": "ivan@example.com",
  "seat_count": 1
}
```

Негативные сценарии:

- `GET /flights` без `origin` или `destination` -> `400`
- `GET /flights/{id}` с невалидным `id` -> `400`
- `GET /bookings/{id}` с несуществующим `id` -> `404`
- `GET /bookings` без `user_id` -> `400`
- `POST /bookings` с `seat_count: 0` -> `400`
- повторный `POST /bookings/{id}/cancel` -> `400`

## Те же проверки через curl

Поиск рейсов:

```bash
curl "http://localhost:8080/flights?origin=SVO&destination=LED&date=2026-04-01"
```

Получение рейса:

```bash
curl "http://localhost:8080/flights/UUID_РЕЙСА"
```

Создание бронирования:

```bash
curl -X POST http://localhost:8080/bookings \
  -H "Content-Type: application/json" \
  -d '{
    "user_id":"user-1",
    "flight_id":"UUID_РЕЙСА",
    "passenger_name":"Ivan Ivanov",
    "passenger_email":"ivan@example.com",
    "seat_count":1
  }'
```

Получение бронирования:

```bash
curl "http://localhost:8080/bookings/UUID_БРОНИ"
```

Список бронирований:

```bash
curl "http://localhost:8080/bookings?user_id=user-1"
```

Отмена бронирования:

```bash
curl -X POST "http://localhost:8080/bookings/UUID_БРОНИ/cancel"
```

## Ручное тестирование gRPC

`flight_service` принимает gRPC на `localhost:50051`.

Для всех вызовов нужен metadata-заголовок:

```text
x-api-key: dev-key
```

Удобнее всего использовать `grpcurl`.

Установка на macOS:

```bash
brew install grpcurl
```

Поиск рейсов:

```bash
grpcurl \
  -plaintext \
  -H 'x-api-key: dev-key' \
  -import-path 'flight_service/proto' \
  -proto 'flight_service/proto/flight_service.proto' \
  -d '{"origin":"SVO","destination":"LED","departure_date":"2026-04-01T00:00:00Z"}' \
  localhost:50051 \
  flight.v1.FlightService/SearchFlights
```

Получение рейса:

```bash
grpcurl \
  -plaintext \
  -H 'x-api-key: dev-key' \
  -import-path 'flight_service/proto' \
  -proto 'flight_service/proto/flight_service.proto' \
  -d '{"flight_id":"UUID_РЕЙСА"}' \
  localhost:50051 \
  flight.v1.FlightService/GetFlight
```

Резерв мест:

```bash
grpcurl \
  -plaintext \
  -H 'x-api-key: dev-key' \
  -import-path 'flight_service/proto' \
  -proto 'flight_service/proto/flight_service.proto' \
  -d '{"flight_id":"UUID_РЕЙСА","booking_id":"UUID_БРОНИ","seat_count":1}' \
  localhost:50051 \
  flight.v1.FlightService/ReserveSeats
```

Отмена резерва:

```bash
grpcurl \
  -plaintext \
  -H 'x-api-key: dev-key' \
  -import-path 'flight_service/proto' \
  -proto 'flight_service/proto/flight_service.proto' \
  -d '{"booking_id":"UUID_БРОНИ"}' \
  localhost:50051 \
  flight.v1.FlightService/ReleaseReservation
```

## Базы данных

Подключения к PostgreSQL:

- `flight_db`
  - host: `localhost`
  - port: `5433`
  - database: `flight_db`
  - user: `flight_user`
  - password: `flight_pass`
- `booking_db`
  - host: `localhost`
  - port: `5434`
  - database: `booking_db`
  - user: `booking_user`
  - password: `booking_pass`

Подключение к Redis:

- host: `localhost`
- port: `6379`
- password: пустой

## Как добавить новый рейс

Отдельной HTTP или gRPC ручки для создания рейса сейчас нет, поэтому новые рейсы добавляются напрямую в `flight_db`.

Пример SQL:

```sql
INSERT INTO flights (
  airline,
  flight_number,
  origin,
  destination,
  departure_time,
  arrival_time,
  total_seats,
  available_seats,
  price_cents,
  status,
  flight_date
) VALUES (
  'S7 Airlines',
  'S71001',
  'SVO',
  'KZN',
  '2026-04-02 10:00:00',
  '2026-04-02 11:30:00',
  150,
  150,
  390000,
  'SCHEDULED',
  '2026-04-02'
);
```

Проверка:

```bash
curl "http://localhost:8080/flights?origin=SVO&destination=KZN&date=2026-04-02"
```

## Интеграционные тесты

Поднять сервисы:

```bash
docker compose -f docker-compose.yml up -d
```

Запустить тесты:

```bash
GOFLAGS="-tags=integration" go test ./tests/integration -v
```
