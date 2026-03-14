from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_env: str = "dev"
    database_url: str = "postgresql+psycopg2://marketplace:marketplace@localhost:5432/marketplace"
    jwt_secret_key: str = "change_me_access"
    jwt_refresh_secret_key: str = "change_me_refresh"
    access_token_expires_minutes: int = 30
    refresh_token_expires_days: int = 14
    order_rate_limit_minutes: int = 5

    class Config:
        env_file = ".env"


settings = Settings()
