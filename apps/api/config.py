"""Конфигурация API через .env (§34)."""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_env: str = "dev"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    processing_version: str = "v1"
    tz_seed: int = 42
    model_dir: str = "./models"
    ensemble_w_gbm: float = 0.55
    ensemble_w_temporal: float = 0.30
    ensemble_w_seasonal: float = 0.15

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
