Marketplace API (OpenAPI + CRUD)

1) Собрать и запустить

- docker-compose up --build

2) Сгенерировать модели 

- ./app/scripts/generate_openapi_models.sh

3) Применить миграции

- docker-compose exec app alembic upgrade head

Документация

- OpenAPI spec: app/src/resources/openapi/marketplace.yaml
- FastAPI http://localhost:8000
- Swagger UI http://localhost:8000/docs


Notes

- Сгенерированные модели лежат в app/src/generated и не коммитятся в git
